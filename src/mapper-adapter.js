/**
 * Adapter for the Mac LiDAR mapper in lidar/mapper (the pipeline run on the real phone).
 *
 * The mapper sends its accumulated map to this viewer in the older sonar
 * envelope, marked `frame.meta.kind: "lidar_map"`. Points are X forward,
 * Y left, Z up, meters. The fourth value is the number of times a map cell was
 * hit (capped at 50), or exactly 100 for points of the live depth frame drawn
 * on top of the map.
 *
 * This module turns those messages into viewer frames with the room
 * classifier's surface classes, so Room analysis works on the mapper's output.
 * It adds nothing to the data: no pose, path or coverage is invented, because
 * the mapper does not send them on this channel.
 */
import { classifyRoom, colorsFor } from './room-classifier.js';

export const MAPPER_MAX_POINTS = 60000;
const LIVE_COLOR = [1, 0.36, 0.25];
const finite = n => typeof n === 'number' && Number.isFinite(n) && Math.abs(n) <= 1000;

/**
 * Median distance to the nearest neighbour, from a sample of points.
 * The mapper keeps one point per grid cube and enlarges the cube as the map
 * grows. For that kind of thinning the cube edge is about 1.6 times this value.
 */
export function pointSpacing(points) {
  const n = points.length / 3;
  if (n < 20) return 0.05;
  const cell = 0.3, grid = new Map();
  const key = (x, y, z) => `${Math.floor(x / cell)},${Math.floor(y / cell)},${Math.floor(z / cell)}`;
  for (let i = 0; i < n; i++) {
    const k = key(points[i * 3], points[i * 3 + 1], points[i * 3 + 2]);
    let list = grid.get(k);
    if (!list) grid.set(k, list = []);
    list.push(i);
  }
  const step = Math.max(1, Math.floor(n / 300)), nearest = [];
  for (let i = 0; i < n; i += step) {
    const x = points[i * 3], y = points[i * 3 + 1], z = points[i * 3 + 2];
    let best = Infinity;
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
      for (const j of grid.get(key(x + dx * cell, y + dy * cell, z + dz * cell)) ?? []) {
        if (j !== i) best = Math.min(best, Math.hypot(points[j * 3] - x, points[j * 3 + 1] - y, points[j * 3 + 2] - z));
      }
    }
    if (best < Infinity) nearest.push(best);
  }
  nearest.sort((a, b) => a - b);
  return nearest.length ? nearest[nearest.length >> 1] : 0.05;
}

/** Classifier steps matched to how coarsely the map was thinned. */
export function classifierSteps(nearest) {
  const layer = Math.min(0.2, Math.max(0.05, Math.ceil(nearest * 1.6 / 0.05 - 0.2) * 0.05));
  return { layer, column: Math.max(0.1, layer * 2), floorBand: Math.max(0.1, layer), ceilingBand: Math.max(0.12, layer),
    objectClearance: Math.max(0.12, layer), minSupportHits: 10, minSupport: 4, minObjectCells: layer > 0.05 ? 3 : 6,
    minObjectPoints: layer > 0.05 ? 8 : 15, minObjectDensity: layer > 0.05 ? 1 : 2.5 };
}

export function createMapperSession() {
  let analysis = classifyRoom(new Float32Array()), signature = '';
  return {
    /** Latest room classification of the map points. See src/room-classifier.js. */
    get analysis() { return analysis; },
    reset() {
      analysis = classifyRoom(new Float32Array());
      signature = '';
    },
    /** Returns a viewer frame for mapper map messages, or undefined for any other payload. */
    async decode(payload) {
      if (payload instanceof Blob) payload = await payload.text();
      if (payload instanceof ArrayBuffer) payload = new TextDecoder().decode(payload);
      if (typeof payload !== 'string' || payload.length > 6_000_000) return undefined;
      let raw;
      try { raw = JSON.parse(payload); } catch { return undefined; }
      if (raw?.type !== 'sonar_frame' || raw.frame?.meta?.kind !== 'lidar_map') return undefined;
      const rows = raw.frame.points;
      if (raw.protocol_version !== '0.1' || !Number.isSafeInteger(raw.sequence) || !Number.isFinite(raw.timestamp) ||
          !Array.isArray(rows) || rows.length > MAPPER_MAX_POINTS) throw new Error('Invalid mapper frame');
      let mapCount = 0;
      for (const row of rows) {
        if (!Array.isArray(row) || row.length !== 4 || !row.every(finite) || row[3] < 0) throw new Error('Invalid mapper point');
        if (row[3] < 100) mapCount++;
      }
      // Map points first, live-frame points after, each converted to the viewer's Y-up axes.
      const points = new Float32Array(rows.length * 3), hits = new Uint16Array(rows.length);
      let m = 0, l = mapCount, hitSum = 0;
      for (const [x, y, z, strength] of rows) {
        const i = strength < 100 ? m++ : l++;
        points.set([-y, z, -x], i * 3);
        if (strength < 100) { hits[i] = strength; hitSum += strength; }
      }
      const map = points.subarray(0, mapCount * 3);
      // The mapper resends the same thinned map until it grows by 2%, so classify only on change.
      const next = `${mapCount}:${map[0]}:${map[map.length - 1]}:${hitSum}`;
      if (next !== signature) {
        signature = next;
        analysis = classifyRoom(map, { hits: hits.subarray(0, mapCount), ...classifierSteps(pointSpacing(map)) });
      }
      const colors = new Float32Array(rows.length * 3);
      colors.set(colorsFor(analysis.labels, mapCount));
      for (let i = mapCount; i < rows.length; i++) colors.set(LIVE_COLOR, i * 3);
      return { points, colors, hits, frame: raw.sequence, captureTime: raw.timestamp,
        snr: mapCount ? hitSum / mapCount : null,
        sonar: { delivery: 'live', acquisition: 'live', detectionCount: null },
        mapper: { mapPoints: mapCount, livePoints: rows.length - mapCount, objects: analysis.objects.length,
          floorArea: analysis.floorArea, roomHeight: analysis.roomHeight } };
    },
  };
}
