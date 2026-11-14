// Coordinates in meters, with Y up. Dimensions are inferred from the references.
export const anchors = [[-2.8, 0, 1.9], [0.7, 0, -1.45], [3.3, 0, 1.15]];
const blue = [0.24, 0.64, 0.98];
const wall = [0.12, 0.38, 0.57];
const floor = [0.11, 0.36, 0.55];
const cream = [0.69, 0.65, 0.55];
const wood = [0.55, 0.36, 0.19];

function random(seed) {
  return () => {
    seed = Math.imul(1664525, seed) + 1013904223 | 0;
    return (seed >>> 0) / 4294967296;
  };
}

export function buildRoom() {
  const rng = random(7281);
  const points = [], meshes = [];
  function surface(project, nu, nv, tint, natural, material = 1, keep = () => true) {
    const sampled = [], mesh = [];
    for (let j = 0; j < nv; j++) {
      for (let i = 0; i < nu; i++) {
        const u = (i + rng()) / nu, v = (j + rng()) / nv;
        if (!keep(u, v, rng())) continue;
        const p = project(u, v);
        const edge = Math.min(u * nu, (1 - u) * nu, v * nv, (1 - v) * nv) < 1.2;
        const gain = material * (0.55 + rng() * 0.62 + (edge ? 0.46 : 0));
        p[0] += (rng() - 0.5) * 0.016;
        p[1] += (rng() - 0.5) * 0.016;
        p[2] += (rng() - 0.5) * 0.016;
        sampled.push([...p, ...tint.map(n => n * gain), ...natural.map(n => n * gain)]);
      }
    }
    points.push(...sampled);
    const nx = Math.max(2, Math.round(nu / 3.8)), ny = Math.max(2, Math.round(nv / 3.8));
    const vertex = (i, j) => {
      const u = (i + (i > 0 && i < nx ? (rng() - 0.5) * 0.7 : 0)) / nx;
      const v = (j + (j > 0 && j < ny ? (rng() - 0.5) * 0.7 : 0)) / ny;
      return project(u, v);
    };
    const lattice = Array.from({ length: ny + 1 }, (_, j) =>
      Array.from({ length: nx + 1 }, (_, i) => vertex(i, j)));
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        if (!keep((i + 0.5) / nx, (j + 0.5) / ny, 0.05)) continue;
        const [a, b, c, d] = [lattice[j][i], lattice[j][i + 1], lattice[j + 1][i], lattice[j + 1][i + 1]];
        const color = tint.map(n => n * 0.85 + 0.12);
        for (const p of [a, b, a, c, b, c, c, d, b, d]) mesh.push(...p, ...color, ...natural);
      }
    }
    for (const value of mesh) meshes.push(value);
  }

  function box(center, dimensions, options = {}) {
    const { radius = 0, yaw = 0, pitch = 0, tint = blue, natural = cream,
      density = 52, strength = 1 } = options;
    const half = dimensions.map(n => n / 2);
    const narrow = half.map(n => Math.max(n - radius, 0));
    for (let axis = 0; axis < 3; axis++) {
      const a = (axis + 1) % 3, b = (axis + 2) % 3;
      for (const sign of [-1, 1]) {
        surface((u, v) => {
          const p = [0, 0, 0];
          p[axis] = sign * half[axis];
          p[a] = (2 * u - 1) * half[a];
          p[b] = (2 * v - 1) * half[b];
          if (radius) {
            const core = p.map((n, i) => Math.max(-narrow[i], Math.min(narrow[i], n)));
            const off = p.map((n, i) => n - core[i]);
            const scale = radius / (Math.hypot(...off) || 1);
            p.forEach((_, i) => { p[i] = core[i] + off[i] * scale; });
          }
          const y = p[1] * Math.cos(pitch) - p[2] * Math.sin(pitch);
          const z = p[1] * Math.sin(pitch) + p[2] * Math.cos(pitch);
          return [center[0] + p[0] * Math.cos(yaw) + z * Math.sin(yaw), center[1] + y,
            center[2] - p[0] * Math.sin(yaw) + z * Math.cos(yaw)];
        }, Math.ceil(dimensions[a] * density), Math.ceil(dimensions[b] * density),
        tint, natural, strength * (axis === 1 && sign === -1 ? 0.52 : axis === 1 ? 1.17 : 0.86));
      }
    }
  }

  // Rear wall, opening, and the right wall with a recessed window.
  surface((u, v) => [u * 8.6 - 4.3, v * 3.15, -3], 240, 99, wall, cream, 0.86,
    (u, v, n) => !(u > 0.09 && u < 0.247 && v < 0.68) &&
      (n < 0.57 || v > 0.97 || u > 0.97 || u < 0.02));
  surface((u, v) => [4.3, v * 3.15, u * 6.4 - 3], 166, 95, wall, cream, 0.7,
    (u, v, n) => !(u > 0.12 && u < 0.53 && v > 0.34 && v < 0.85) &&
      (n < 0.63 || v > 0.97 || u > 0.97 || u < 0.02));
  surface((u, v) => [u * 8.6 - 4.3, 0, v * 6.4 - 3], 222, 175, floor, wood, 0.98,
    (u, v, n) => n < 0.26 + v * 0.66 + 0.12 * Math.sin(27 * u + 9 * v));
  surface((u, v) => [u * 8.6 - 4.3, 3.15, v * 1.7 - 3], 180, 36, wall, cream, 0.65,
    (u, v, n) => n < (1 - v) * 0.72);

  const rail = (center, dims) => box(center, dims, { tint: [0.22, 0.58, 0.81], natural: wood, density: 42 });
  for (const x of [-3.53, -2.19]) rail([x, 1.07, -2.94], [0.08, 2.14, 0.12]);
  rail([-2.86, 2.14, -2.94], [1.42, 0.09, 0.13]);
  rail([0, 3.14, -2.98], [8.6, 0.032, 0.06]);
  rail([4.27, 3.14, 0.2], [0.06, 0.032, 6.4]);
  for (const z of [-2.22, -0.93, 0.39]) rail([4.22, 1.87, z], [0.10, 1.66, 0.055]);
  for (const y of [1.05, 2.70]) rail([4.22, y, -0.92], [0.12, 0.055, 2.68]);
  for (let i = 0; i < 10; i++) {
    box([4.14 - Math.sin(i * 1.5) * 0.035, 1.84, -2.15 + i * 0.026], [0.08, 1.64, 0.019],
      { tint: [0.19, 0.49, 0.68], density: 26, strength: 0.75 });
  }

  // Three separate seat cushions and tilted backs, rounded arms and feet.
  function couch(x, z, count, yaw = 0) {
    const width = count * 0.89 + 0.44;
    const p = (u, y, v) => [x + u * Math.cos(yaw) + v * Math.sin(yaw), y,
      z - u * Math.sin(yaw) + v * Math.cos(yaw)];
    const fabric = [0.44, 0.52, 0.56];
    box(p(0, 0.24, 0), [width, 0.29, 0.94], { yaw, radius: 0.065, natural: fabric, density: 45 });
    for (const sign of [-1, 1]) {
      box(p(sign * (width / 2 - 0.11), 0.48, 0), [0.22, 0.55, 0.99],
        { yaw, radius: 0.055, natural: fabric });
      for (const v of [-0.32, 0.32]) {
        box(p(sign * (width / 2 - 0.17), 0.08, v), [0.09, 0.16, 0.09], { yaw, natural: wood });
      }
    }
    for (let i = 0; i < count; i++) {
      const u = (i - (count - 1) / 2) * 0.89;
      box(p(u, 0.44, 0.10), [0.86, 0.19, 0.69], { yaw, radius: 0.055, natural: fabric });
      box(p(u, 0.79, -0.33), [0.85, 0.58, 0.19],
        { yaw, pitch: 0.19, radius: 0.065, natural: fabric });
    }
  }
  couch(-0.34, -2.13, 3);
  couch(3.05, 1.42, 1, -1.16);
  rail([-0.42, 2.0, -2.91], [1.43, 0.84, 0.065]);
  box([-0.42, 2.0, -2.87], [1.29, 0.70, 0.014], {
    tint: [0.13, 0.34, 0.51], natural: [0.28, 0.4, 0.51], density: 35,
  });

  // The open lower shelf and separate legs leave readable gaps in the table.
  for (const y of [0.13, 0.51]) box([0.32, y, 0.29], [1.73, 0.084, 0.79],
    { radius: 0.02, density: 53, natural: wood });
  for (const x of [-0.45, 1.09]) {
    for (const z of [-0.025, 0.60]) box([x, 0.24, z], [0.085, 0.48, 0.085], { natural: wood });
  }
  box([0.17, 0.573, 0.23], [0.47, 0.027, 0.29], { yaw: 0.19, natural: cream, density: 55 });

  // Bookshelves with separate books and uneven heights, along the right wall.
  for (const z of [1.91, 3.14]) box([4.1, 1.15, z], [0.35, 2.30, 0.06], { natural: wood });
  for (let i = 0; i < 5; i++) {
    const y = 0.14 + i * 0.53;
    box([4.08, y, 2.52], [0.40, 0.067, 1.27], { natural: wood });
    if (i === 4) continue;
    for (let k = 0; k < 12; k++) {
      if ((k + i * 2) % 7 < 2) continue;
      const h = 0.21 + rng() * 0.19;
      box([3.98 + rng() * 0.03, y + 0.035 + h / 2, 1.99 + k * 0.097],
        [0.23, h, 0.047 + rng() * 0.032],
        { pitch: (k % 4 === 0 ? 0.16 : -0.022), natural: [0.42 + rng() * 0.28, 0.41, 0.38], density: 48 });
    }
  }
  const lamp = [2.11, -2.42];
  for (let i = 0; i < 3; i++) {
    const [y, radius, height] = [[0.04, 0.24, 0.06], [0.84, 0.025, 1.66], [1.75, 0.26, 0.32]][i];
    surface((u, v) => {
      const theta = u * 2 * Math.PI, r = i === 2 ? radius * (1 - 0.31 * v) : radius;
      return [lamp[0] + r * Math.cos(theta), y + (v - 0.5) * height, lamp[1] + r * Math.sin(theta)];
    }, i === 2 ? 68 : 28, Math.ceil(height * 44), blue, i === 2 ? cream : wood);
  }

  // Uniform draw prefixes preserve coverage when the user lowers the point cap.
  for (let i = points.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [points[i], points[j]] = [points[j], points[i]];
  }
  const cloud = new Float32Array(Math.min(100000, points.length) * 9);
  for (let i = 0; i < cloud.length / 9; i++) cloud.set(points[i], i * 9);
  // Shuffle groups of lines so the cap reduces detail across the room evenly.
  const mesh = new Float32Array(meshes);
  const chunk = 90;
  const temp = new Float32Array(chunk);
  for (let i = mesh.length - chunk; i > 0; i -= chunk) {
    const j = Math.floor(rng() * (i / chunk + 1)) * chunk;
    temp.set(mesh.subarray(i, i + chunk));
    mesh.copyWithin(i, j, j + chunk);
    mesh.set(temp, j);
  }
  return { cloud, mesh };
}
