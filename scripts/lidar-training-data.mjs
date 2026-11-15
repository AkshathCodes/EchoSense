import { createSpatialMemory } from '../src/spatial-memory.js';
import { FLOOR, WALL, CEILING, OBJECT } from '../src/room-classifier.js';

export function rng(seed) {
  return () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296);
}

// Seed controls dimensions, furniture, camera sweep, point density, noise, and missed returns.
// A label is assigned to the ray's actual first surface before noisy projection.
export function syntheticScan(seed, { frames, rough = false } = {}) {
  const random = rng(seed), between = (a, b) => a + (b - a) * random();
  const wx = between(1.7, 3.25), wz = between(1.6, 2.9), floor = between(-1.65, -1.05);
  const ceiling = floor + between(2.2, 3.15), lookUp = random() > 0.2;
  const noise = between(0.005, rough ? 0.033 : 0.024), outliers = between(0.006, rough ? 0.085 : 0.04);
  const angle = between(-0.38, 0.38), cos = Math.cos(angle), sin = Math.sin(angle);
  const shiftX = between(-1, 1), shiftZ = between(-1, 1);
  const world = ([x, y, z]) => [Math.fround(x * cos - z * sin + shiftX), Math.fround(y), Math.fround(x * sin + z * cos + shiftZ)];
  const boxes = [1, -1, 1, -1].slice(0, 2 + Math.floor(between(0, 3))).map((side, i) => {
    const cx = side * wx * between(0.39, 0.68), cz = wz * (i < 2 ? 1 : -1) * between(0.24, 0.67);
    const a = between(0.22, 0.54), b = between(0.2, 0.46), h = between(0.34, i === 3 ? 1.62 : 1.08);
    return [[cx - a, floor, cz - b], [cx + a, floor + h, cz + b]];
  });
  const memory = createSpatialMemory(), truth = new Map();
  const voxel = p => p.map(x => Math.floor(x / 0.05)).join(',');
  const sweep = between(0.10, 0.20), phase = between(0, 6.28), count = frames ?? Math.floor(between(36, 101));
  for (let f = 0; f < count; f++) {
    const camera = [0.35 * Math.sin(f / 21), 0.12 * Math.sin(f / 17), 0.47 * Math.cos(f / 21)];
    const yaw = phase + f * sweep, pitch = (lookUp ? -0.13 : -0.49) + 0.30 * Math.sin(f / 12);
    const points = [], confidences = [];
    for (let r = 0; r < 23; r++) for (let c = 0; c < 31; c++) {
      if (random() < (rough ? 0.21 : 0.10)) continue;
      const az = yaw + (c / 30 - 0.5) * 1.05, el = pitch + (0.5 - r / 22) * 0.85;
      const d = [-Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el)];
      let best = Infinity, label = 0;
      for (const [axis, lo, hi, lowLabel, highLabel] of [[0, -wx, wx, WALL, WALL], [1, floor, ceiling, FLOOR, CEILING], [2, -wz, wz, WALL, WALL]]) {
        const t = ((d[axis] > 0 ? hi : lo) - camera[axis]) / d[axis];
        if (t > 0 && t < best) { best = t; label = d[axis] > 0 ? highLabel : lowLabel; }
      }
      for (const [lo, hi] of boxes) {
        let near = 0, far = best;
        for (let a = 0; a < 3; a++) {
          const t1 = (lo[a] - camera[a]) / d[a], t2 = (hi[a] - camera[a]) / d[a];
          near = Math.max(near, Math.min(t1, t2)); far = Math.min(far, Math.max(t1, t2));
        }
        if (near > 0.05 && near <= far) { best = near; label = OBJECT; }
      }
      if (best > 5) continue;
      let range = best + (random() + random() + random() - 1.5) * noise * (1 + best / 3);
      if (random() < outliers) { range *= between(0.55, 1.55); label = 0; }
      const point = world(camera.map((x, i) => x + range * d[i])), k = voxel(point);
      if (!truth.has(k)) truth.set(k, label);
      points.push(point); confidences.push(2);
    }
    memory.addFrame({ points, confidences, camera: world(camera), tracking: 'normal' });
  }
  const points = memory.cloud(), labels = new Uint8Array(points.length / 3);
  for (let i = 0; i < labels.length; i++) labels[i] = truth.get(voxel(points.subarray(i * 3, i * 3 + 3))) ?? 0;
  return { points, hits: memory.hits(), labels };
}
