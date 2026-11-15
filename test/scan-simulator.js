// SYNTHETIC scan simulator, used by room-classifier.test.js. Not real sensor data.
// Ray-casts a furnished 5 x 4 x 2.5 m room from a moving, turning camera at the
// phone's sampling density (37 x 28 rays, 3 frames a second), adds range noise
// and stray returns, feeds the frames through spatial memory, and scores the
// classifier against the surface each ray really hit.
import { createSpatialMemory } from '../src/spatial-memory.js';
import { classifyRoom, FLOOR, WALL, CEILING, OBJECT, classNames } from '../src/room-classifier.js';

const F = -1.3, C = 1.2, RX = 2.5, RZ = 2.0;
const boxes = [ // x0,x1,y0,y1,z0,z1,label,name
  [1.0, 2.0, F, F + 0.75, -0.3, 0.3, OBJECT, 'table'],
  [-1.8, -1.3, F, F + 0.5, 1.0, 1.5, OBJECT, 'crate'],
  [-1.0, 1.0, F, F + 0.8, -2.0, -1.1, OBJECT, 'sofa on wall'],
  [-2.5, -2.1, F, F + 1.8, -0.4, 0.4, 0, 'tall cabinet'],   // 0 = either WALL or OBJECT is acceptable
];
export function simulate({ seconds = 40, noise = 0.015, outliers = 0.02, lookUp = true, seed = 1, fps = 3 } = {}) {
  let s = seed; const rnd = () => (s = (s * 1664525 + 1013904223) % 4294967296) / 4294967296;
  const gauss = () => Math.sqrt(-2 * Math.log(rnd() + 1e-12)) * Math.cos(6.2831853 * rnd());
  const memory = createSpatialMemory();
  const truth = new Map();   // voxel key -> label, recorded at the first hit (the one memory keeps)
  const vkey = (x, y, z) => `${Math.floor(x / 0.05)},${Math.floor(y / 0.05)},${Math.floor(z / 0.05)}`;
  for (let f = 0; f < seconds * fps; f++) {
    const t = f / fps;
    const cam = [0.7 * Math.sin(t * 0.2), 0.05 * Math.sin(t), 0.5 * Math.cos(t * 0.2) + 0.2];
    const yaw = t * 0.45, pitch0 = lookUp ? -0.25 + 0.45 * Math.sin(t * 0.35) : -0.45 + 0.2 * Math.sin(t * 0.35);
    const points = [], conf = [];
    for (let r = 0; r < 28; r++) for (let c = 0; c < 37; c++) {
      const az = yaw + (c / 36 - 0.5) * 1.05, el = pitch0 + (0.5 - r / 27) * 0.82;
      const d = [-Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el)];
      let best = Infinity, label = 0;
      const hit = (dist, l) => { if (dist > 0.05 && dist < best) { best = dist; label = l; } };
      if (d[0]) hit((d[0] > 0 ? RX - cam[0] : -RX - cam[0]) / d[0], WALL);
      if (d[2]) hit((d[2] > 0 ? RZ - cam[2] : -RZ - cam[2]) / d[2], WALL);
      if (d[1] > 0) hit((C - cam[1]) / d[1], CEILING);
      if (d[1] < 0) hit((F - cam[1]) / d[1], FLOOR);
      for (const b of boxes) {
        let near = 0, far = Infinity, ok = true;
        for (let a = 0; a < 3; a++) {
          if (Math.abs(d[a]) < 1e-9) { if (cam[a] < b[a * 2] || cam[a] > b[a * 2 + 1]) ok = false; continue; }
          const p = (b[a * 2] - cam[a]) / d[a], q = (b[a * 2 + 1] - cam[a]) / d[a];
          near = Math.max(near, Math.min(p, q)); far = Math.min(far, Math.max(p, q));
        }
        if (ok && near <= far) hit(near, b[6] === 0 ? -1 : b[6]);
      }
      if (best > 5) continue;                       // beyond LiDAR range
      let range = best + gauss() * noise * (1 + best / 3), lab = label;
      if (rnd() < outliers) { range = best * (0.6 + rnd() * 0.9); lab = -2; }   // multipath / flying pixel
      const p = [cam[0] + d[0] * range, cam[1] + d[1] * range, cam[2] + d[2] * range];
      points.push(p); conf.push(2);
      const k = vkey(...p); if (!truth.has(k)) truth.set(k, lab);
    }
    memory.addFrame({ points, confidences: conf, camera: cam, tracking: 'normal' });
  }
  return { memory, truth, vkey };
}
export function score(opts, classifierOptions) {
  const { memory, truth, vkey } = simulate(opts);
  const cloud = memory.cloud(), result = classifyRoom(cloud, { hits: memory.hits(), ...classifierOptions });
  const un = result.counts[0];
  const tally = {}; let right = 0, counted = 0;
  for (let i = 0; i < cloud.length / 3; i++) {
    const t = truth.get(vkey(cloud[i * 3], cloud[i * 3 + 1], cloud[i * 3 + 2])), got = result.labels[i];
    if (t === -2 || t === undefined) continue;      // outliers have no right answer
    const name = t === -1 ? 'cabinet' : classNames[t];
    tally[name] ??= { n: 0, ok: 0 };
    tally[name].n++; counted++;
    const ok = t === -1 ? got === WALL || got === OBJECT : got === t;
    if (ok) { tally[name].ok++; right++; }
  }
  return { points: cloud.length / 3, unclassified: un, accuracy: +(right / counted).toFixed(3),
    recall: Object.fromEntries(Object.entries(tally).map(([k, v]) => [k, +(v.ok / v.n).toFixed(2)])),
    floorY: result.floorY && +result.floorY.toFixed(2), height: result.roomHeight && +result.roomHeight.toFixed(2),
    objects: result.objects.map(o => ({ name: o.name, x: +o.center[0].toFixed(2), z: +o.center[1].toFixed(2),
      width: +o.width.toFixed(1), depth: +o.depth.toFixed(1), height: +o.height.toFixed(2) })) };
}
