// Features from observed metric geometry only. Training and browser use the same code.
export const FEATURE_COUNT = 12;
const GRID = 0.12, STRIDE = 32768;
const key = (x, y, z) => ((x + 16384) * STRIDE + y + 16384) * STRIDE + z + 16384;

// A quick evidence-based floor offset, independent of replay speed and analysis cadence.
export function lidarFloorOffset(points, hits, fallback) {
  const bands = new Map();
  for (let i = 0; i < points.length / 3; i++) {
    const y = points[i * 3 + 1], k = Math.floor(y / 0.05);
    let band = bands.get(k);
    if (!band) bands.set(k, band = [0, 0, 0]);
    band[0]++; band[1] += Math.min(hits[i], 4); band[2] += y;
  }
  const threshold = Math.max(20, points.length / 3 * 0.004);
  const first = [...bands.keys()].sort((a, b) => a - b).find(k => {
    const a = bands.get(k), b = bands.get(k + 1) ?? [0, 0];
    return a[0] + b[0] >= threshold && a[1] + b[1] >= threshold * 1.3;
  });
  if (first === undefined) return fallback;
  const a = bands.get(first), b = bands.get(first + 1) ?? [0, 0, 0];
  return (a[2] + b[2]) / (a[0] + b[0]);
}

export function lidarFeatures(points, hits, baseline) {
  const n = points.length / 3, cells = new Map(), columns = new Map(), layers = new Map();
  const indices = new Float64Array(n), columnIds = new Float64Array(n), layerIds = new Int32Array(n);
  const vertical = STRIDE, lateral = STRIDE * STRIDE, features = new Float32Array(n * FEATURE_COUNT);
  const floor = baseline.floorY ?? 0;
  for (let i = 0; i < n; i++) {
    const x = Math.floor(points[3 * i] / GRID), y = points[3 * i + 1], z = Math.floor(points[3 * i + 2] / GRID);
    const cell = key(x, Math.floor((y - floor) / GRID), z), column = key(x, 0, z), layer = Math.floor((y - floor) / 0.045);
    indices[i] = cell; columnIds[i] = column; layerIds[i] = layer;
    cells.set(cell, (cells.get(cell) ?? 0) + Math.min(hits?.[i] ?? 1, 16));
    layers.set(layer, (layers.get(layer) ?? 0) + 1);
    if (baseline.labels[i]) {
      let c = columns.get(column);
      if (!c) columns.set(column, c = [y, y, 0]);
      c[0] = Math.min(c[0], y); c[1] = Math.max(c[1], y); c[2]++;
    }
  }
  const support = new Map(), count = id => cells.get(id) ?? 0;
  for (let i = 0; i < n; i++) {
    const cell = indices[i], y = points[3 * i + 1], c = columns.get(columnIds[i]), layer = layerIds[i];
    let values = support.get(cell);
    if (!values) {
      let near = 0, horizontal = 0, upright = 0;
      for (let dx = -1; dx <= 1; dx++) for (let dz = -1; dz <= 1; dz++) {
        const row = cell + dx * lateral + dz;
        horizontal += count(row);
        near += count(row) + count(row - vertical) + count(row + vertical);
      }
      for (let dy = -2; dy <= 2; dy++) upright += count(cell + dy * vertical);
      values = [Math.log1p(near), horizontal / Math.max(near, 1), upright / Math.max(near, 1)];
      support.set(cell, values);
    }
    const o = i * FEATURE_COUNT;
    features[o] = y - floor;
    features[o + 1] = baseline.ceilingY === null ? 4 : baseline.ceilingY - y;
    features[o + 2] = baseline.labels[i];
    features[o + 3] = Math.log1p(hits?.[i] ?? 1);
    features[o + 4] = values[0];
    features[o + 5] = values[1];
    features[o + 6] = values[2];
    features[o + 7] = c ? c[1] - c[0] : 0;
    features[o + 8] = c ? c[1] - floor : 0;
    features[o + 9] = c ? Math.log1p(c[2]) : 0;
    features[o + 10] = ((layers.get(layer - 1) ?? 0) + (layers.get(layer) ?? 0) + (layers.get(layer + 1) ?? 0)) / n;
    features[o + 11] = c ? (y - c[0]) / Math.max(c[1] - c[0], 0.05) : 0;
  }
  return features;
}
