/**
 * Spatial memory for LiDAR sessions: what was observed, from where, and what was not.
 *
 * Coordinates are ARKit world meters (+Y up), exactly as received. Nothing here
 * rotates or rescales them.
 *
 * Three records are kept, all bounded:
 *  - surface voxels: one retained point per occupied 5 cm cube
 *  - trajectory: where the scanner has been
 *  - plan-view coverage: 25 cm floor-plan cells, each UNKNOWN, SEEN or SURFACE
 *
 * Coverage assumptions, stated because the display depends on them:
 *  - A cell is SEEN when at least one sensor ray crossed it in plan view, at any
 *    height. That is evidence the ray's path was open at that height, not that
 *    the cell is empty or safe from floor to ceiling.
 *  - A cell is SURFACE when a return landed in it above floor level.
 *  - Every other cell is UNKNOWN. Unknown means no measurement. It makes no claim.
 *  - Frames received while tracking is not "normal" are counted and not stored,
 *    because their world coordinates cannot be trusted.
 */
export const UNKNOWN = 0, SEEN = 1, SURFACE = 2;

const pack = (a, b, c) => ((a + 2048) * 4096 + (b + 2048)) * 4096 + (c + 2048);
const inRange = n => n > -2048 && n < 2048;

export function createSpatialMemory({ voxel = 0.05, maxVoxels = 120000, cell = 0.25,
  minConfidence = 1, maxTrajectory = 4000, raySubsample = 4, floorBand = 0.15 } = {}) {
  let voxels, positions, count, trajectory, pathLength, coverage, floor, integrated, skipped, dropped, revision;

  function clear() {
    voxels = new Map();
    positions = new Float32Array(3 * 4096);
    count = 0;
    trajectory = [];
    pathLength = 0;
    coverage = new Map();
    floor = Infinity;
    integrated = skipped = dropped = 0;
    revision = (revision ?? 0) + 1;
  }
  clear();

  function mark(x, z, state) {
    const cx = Math.floor(x / cell), cz = Math.floor(z / cell);
    if (!inRange(cx) || !inRange(cz)) return;
    const key = pack(cx, 0, cz);
    if ((coverage.get(key) ?? UNKNOWN) < state) coverage.set(key, state);
  }

  /** points: [[x,y,z],...]; confidences: parallel 0..2; camera: [x,y,z]; tracking: string. */
  function addFrame({ points, confidences, camera, tracking }) {
    if (tracking !== 'normal') {
      skipped++;
      return { added: 0, stored: false };
    }
    integrated++;
    const last = trajectory.at(-1);
    const moved = last ? Math.hypot(camera[0] - last[0], camera[1] - last[1], camera[2] - last[2]) : Infinity;
    if (moved > 0.05) {
      if (last) pathLength += moved;
      trajectory.push([camera[0], camera[1], camera[2]]);
      // Thin the oldest half instead of forgetting where the scan began.
      if (trajectory.length > maxTrajectory) trajectory = trajectory.filter((_, i) => i % 2 === 0 || i > maxTrajectory / 2);
    }
    mark(camera[0], camera[2], SEEN);
    let added = 0;
    for (let i = 0; i < points.length; i++) {
      if ((confidences?.[i] ?? 2) < minConfidence) continue;
      const [x, y, z] = points[i];
      if (y < floor) floor = y;
      const ix = Math.floor(x / voxel), iy = Math.floor(y / voxel), iz = Math.floor(z / voxel);
      if (!inRange(ix) || !inRange(iy) || !inRange(iz)) continue;
      const key = pack(ix, iy, iz);
      if (!voxels.has(key)) {
        if (count >= maxVoxels) {
          dropped++;
        } else {
          if (count * 3 >= positions.length) {
            const grown = new Float32Array(Math.min(maxVoxels * 3, positions.length * 2));
            grown.set(positions);
            positions = grown;
          }
          positions.set([x, y, z], count * 3);
          voxels.set(key, count++);
          added++;
        }
      }
      if (i % raySubsample === 0) {
        // March the plan-view ray from scanner to return, then classify the end cell.
        const dx = x - camera[0], dz = z - camera[2];
        const steps = Math.ceil(Math.hypot(dx, dz) / (cell / 2));
        for (let s = 1; s < steps; s++) mark(camera[0] + dx * s / steps, camera[2] + dz * s / steps, SEEN);
        mark(x, z, y > floor + floorBand ? SURFACE : SEEN);
      }
    }
    if (added || moved > 0.05) revision++;
    return { added, stored: true };
  }

  return {
    addFrame, clear, voxel, cell,
    /** Changes whenever stored geometry or trajectory changes. */
    get revision() { return revision; },
    get count() { return count; },
    get floor() { return Number.isFinite(floor) ? floor : 0; },
    get trajectory() { return trajectory; },
    /** Copy of retained points as flat XYZ, optionally lifted by `lift` meters in Y. */
    cloud(lift = 0) {
      const out = positions.slice(0, count * 3);
      if (lift) for (let i = 1; i < out.length; i += 3) out[i] += lift;
      return out;
    },
    /** Visits each recorded plan-view cell: (cellX, cellZ, state). Unknown cells are not stored. */
    eachCell(visit) {
      for (const [key, state] of coverage) {
        visit(Math.floor(key / 16777216) - 2048, key % 4096 - 2048, state);
      }
    },
    stats() {
      let seen = 0, surface = 0;
      for (const state of coverage.values()) state === SURFACE ? surface++ : seen++;
      return { voxels: count, dropped, framesStored: integrated, framesSkipped: skipped,
        pathMeters: pathLength, cellsSeen: seen, cellsSurface: surface,
        observedArea: (seen + surface) * cell * cell };
    },
  };
}
