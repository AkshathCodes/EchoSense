import { classifyRoom, FLOOR, WALL, CEILING, OBJECT } from './room-classifier.js';
import { lidarFeatures } from './lidar-features.js';
import { predictLidar } from './lidar-predict.js';
import { lidarModel } from './lidar-model.js';

/** Keep class labels, measured footprints and uncertainty in the same coordinates. */
export function analyseLidar(points, { hits, baselineOptions } = {}) {
  const baseline = classifyRoom(points, { ...baselineOptions, hits }), n = points.length / 3;
  const labels = new Uint8Array(n), counts = [0, 0, 0, 0, 0], votes = new Uint8Array(counts.length);
  const { column, floorY } = baseline;
  const cells = counts.map(() => new Map()), ceiling = [];
  const features = floorY === null ? null : lidarFeatures(points, hits, baseline);
  for (let i = 0; i < n; i++) {
    const [x, y, z] = [points[i * 3], points[i * 3 + 1], points[i * 3 + 2]];
    const label = features ? predictLidar(features, i, lidarModel, votes) : 0;
    labels[i] = label;
    counts[label]++;
    if (label === CEILING) ceiling.push(y);
    const cx = Math.floor(x / column), cz = Math.floor(z / column), k = cx * 65536 + cz + 32768;
    let cell = cells[label].get(k);
    if (!cell) cells[label].set(k, cell = { xy: [cx, cz], heights: [] });
    if (label === OBJECT && y - floorY >= (baselineOptions?.objectClearance ?? 0)) cell.heights.push(y - floorY);
  }
  const objects = [], seen = new Set(), objectCells = cells[OBJECT];
  for (const start of objectCells.keys()) {
    if (seen.has(start) || !objectCells.get(start).heights.length) continue;
    const queue = [start], footprint = [], heights = [];
    let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
    seen.add(start);
    for (const k of queue) {
      const { xy, heights: samples } = objectCells.get(k), [x, z] = xy;
      footprint.push(xy);
      for (const height of samples) heights.push(height);
      x0 = Math.min(x0, x); x1 = Math.max(x1, x); z0 = Math.min(z0, z); z1 = Math.max(z1, z);
      for (let dx = -1; dx <= 1; dx++) for (let dz = -1; dz <= 1; dz++) {
        const neighbor = k + dx * 65536 + dz;
        if (objectCells.get(neighbor)?.heights.length && !seen.has(neighbor)) { seen.add(neighbor); queue.push(neighbor); }
      }
    }
    if (footprint.length < (baselineOptions?.minObjectCells ?? 6) ||
        heights.length < (baselineOptions?.minObjectPoints ?? 15)) continue;
    heights.sort((a, b) => a - b);
    const height = heights[Math.floor((heights.length - 1) * 0.95)];
    objects.push({ cells: footprint, height, points: heights.length, width: (x1 - x0 + 1) * column,
      depth: (z1 - z0 + 1) * column, center: [(x0 + x1 + 1) * column / 2, (z0 + z1 + 1) * column / 2],
      footprint: footprint.length * column ** 2 });
  }
  objects.sort((a, b) => b.footprint - a.footprint);
  objects.forEach((o, i) => { o.name = String.fromCharCode(65 + i % 26) + (i >= 26 ? Math.floor(i / 26) : ''); });
  ceiling.sort((a, b) => a - b);
  const ceilingY = ceiling.length >= 25 && cells[CEILING].size >= 5 ? ceiling[ceiling.length >> 1] : null;
  const [uncertainCells, floorCells, wallCells, ceilingCells, returnsFromObjects] =
    cells.map(layer => Array.from(layer.values(), cell => cell.xy));
  return { model: lidarModel.name, labels, counts, column, floorY, ceilingY, floorCells, wallCells,
    ceilingCells, uncertainCells, objectCells: returnsFromObjects, objects, floorArea: floorCells.length * column ** 2,
    roomHeight: ceilingY === null ? null : ceilingY - floorY };
}
