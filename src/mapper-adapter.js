/**
 * Adapter for the Mac LiDAR mapper in lidar/mapper (the pipeline run on the real phone).
 *
 * The mapper sends its accumulated map to this viewer in the older sonar
 * envelope, marked `frame.meta.kind: "lidar_map"`. Points are X forward,
 * Y left, Z up, meters. The fourth value is the number of times a map cell was
 * hit (capped at 50), exactly 100 for points of the live depth frame drawn on
 * top of the map, or 200 for sonar-only surface points: places where the
 * HC-SR04 heard an echo clearly nearer than anything the LiDAR saw (glass,
 * mirrors). When a sonar is attached, `frame.meta.sonar` carries the latest
 * cross-check (lidar/mapper/src/lidar_mapper/sonar.py).
 *
 * This module turns those messages into viewer frames with the room
 * classifier's surface classes, so Room analysis works on the mapper's output.
 * It adds nothing to the data: no pose, path or coverage is invented, because
 * the mapper does not send them on this channel.
 */
import { classifyRoom, colorsFor } from './room-classifier.js';
import { analyseLidar } from './lidar-analysis.js';

export const MAPPER_MAX_POINTS = 60000;
const LIVE_COLOR = [1, 0.36, 0.25], SONAR_COLOR = [1, 0.25, 0.9];
const sonarStates = ['no_sonar', 'agree', 'sonar_closer', 'lidar_no_return', 'sonar_farther'];
const meters = n => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 100 ? n : null;

/** Delivery is distinct from original acquisition; recorded acquisition means unknown. */
export function mapperLabel({ delivery, acquisition, simulated, stale = false, capture }) {
  // Old saved maps may retain only `simulated`; false alone never proves real acquisition.
  const origin = acquisition === 'simulated' || simulated === true ? 'Simulated LiDAR map'
    : acquisition === 'live' ? 'LiDAR map' : 'LiDAR map / original acquisition unknown';
  const phase = { stalled: ' / capture stalled', disconnected: ' / source disconnected', complete: ' / complete',
    waiting: ' / waiting for depth' }[capture?.state] ?? '';
  return `${stale ? 'Last map / historical / ' : ''}${origin}${delivery === 'recorded' ? ' / replay' : ''}${phase}`;
}

/** Optional additive metadata. Legacy/malformed freshness never proves active capture. */
export function readCaptureStatus(raw) {
  if (!raw || !['live', 'simulated', 'replay', 'unknown'].includes(raw.mode) ||
      !['waiting', 'active', 'stalled', 'disconnected', 'complete'].includes(raw.state) ||
      !(raw.age_s === null || typeof raw.age_s === 'number' && Number.isFinite(raw.age_s) && raw.age_s >= 0) ||
      typeof raw.stall_after_s !== 'number' || !Number.isFinite(raw.stall_after_s) || raw.stall_after_s <= 0) return null;
  // The mapper rounds age to milliseconds before sending it.
  if (raw.state === 'active' && (raw.age_s === null || raw.age_s > raw.stall_after_s + 0.001)) return null;
  return { mode: raw.mode, state: raw.state, age_s: raw.age_s, stall_after_s: raw.stall_after_s };
}

export function captureText(capture) {
  if (!capture) return 'Capture freshness unavailable';
  const mode = { live: 'Phone capture', simulated: 'Simulated capture', replay: 'Replay', unknown: 'Capture (origin unknown)' }[capture.mode];
  const state = { active: 'receiving depth', waiting: 'waiting for depth', stalled: 'stalled',
    disconnected: 'source disconnected', complete: 'complete' }[capture.state];
  return `${mode}: ${state}${capture.age_s === null ? '' : ` / last depth ${capture.age_s.toFixed(1)} s ago`}`;
}

/** Reads `meta.sonar`. Returns null when no sonar is attached or the block is malformed. */
export function readSonarStatus(raw) {
  if (!raw || typeof raw !== 'object' || !sonarStates.includes(raw.state)) return null;
  return { state: raw.state, range: meters(raw.range_m), lidarNear: meters(raw.lidar_near_m),
    lidarMedian: meters(raw.lidar_median_m), surfacePoints: Number.isSafeInteger(raw.surface_points) ? raw.surface_points : 0,
    synthetic: raw.synthetic === true, acquisition: raw.acquisition_source,
    blind: raw.state === 'sonar_closer' || raw.state === 'lidar_no_return' };
}

/** One line for the operator. Says plainly when the readings are simulated. */
export function sonarText(sonar) {
  const tag = sonar.synthetic ? 'Simulated sonar'
    : sonar.acquisition === 'recorded' ? 'Recorded sonar (original acquisition unknown)' : 'Sonar';
  const reading = sonar.range === null ? 'no echo' : `${sonar.range.toFixed(2)} m`;
  const lidar = sonar.lidarNear === null ? 'LiDAR no return' : `LiDAR ${sonar.lidarNear.toFixed(2)} m`;
  const verdict = { agree: 'agree', sonar_closer: 'surface LiDAR cannot see', lidar_no_return: 'surface LiDAR cannot see',
    sonar_farther: 'sonar missed the nearer surface', no_sonar: 'no fresh reading' }[sonar.state];
  return `${tag} ${reading} · ${lidar} · ${verdict}`;
}
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

const sameMap = (scan, points, hits) => scan?.points.length === points.length &&
  points.every((value, i) => value === scan.points[i]) && hits.every((value, i) => value === scan.hits[i]);

export function createMapperSession({ classify = analyseLidar } = {}) {
  let analysis = classifyRoom(new Float32Array()), cached, pending, sonarSurface = new Float32Array();
  return {
    /** Sonar-only surface points from the latest frame, flat XYZ in viewer axes. */
    get sonarSurface() { return sonarSurface; },
    /** Latest room classification of the map points. */
    get analysis() { return analysis; },
    reset() {
      analysis = classifyRoom(new Float32Array());
      cached = pending = undefined;
      sonarSurface = new Float32Array();
    },
    /** Null skips a busy mapper frame; undefined allows another protocol decoder. */
    async decode(payload) {
      if (payload instanceof Blob) payload = await payload.text();
      if (payload instanceof ArrayBuffer) payload = new TextDecoder().decode(payload);
      if (typeof payload !== 'string' || payload.length > 6_000_000) return undefined;
      let raw;
      try { raw = JSON.parse(payload); } catch { return undefined; }
      if (raw?.type !== 'sonar_frame' || raw.frame?.meta?.kind !== 'lidar_map') return undefined;
      const modes = ['live', 'simulated', 'recorded'];
      const acquisition = raw.acquisition_source ?? 'recorded', delivery = raw.source ?? 'recorded';
      const capture = readCaptureStatus(raw.frame.meta.capture);
      if (!modes.includes(delivery) || !modes.includes(acquisition)) throw new Error('Invalid mapper provenance');
      const rows = raw.frame.points;
      if (raw.protocol_version !== '0.1' || !Number.isSafeInteger(raw.sequence) || !Number.isFinite(raw.timestamp) ||
          !Array.isArray(rows) || rows.length > MAPPER_MAX_POINTS) throw new Error('Invalid mapper frame');
      let mapCount = 0, sonarCount = 0;
      for (const row of rows) {
        if (!Array.isArray(row) || row.length !== 4 || !row.every(finite) || row[3] < 0) throw new Error('Invalid mapper point');
        if (row[3] < 100) mapCount++;
        else if (row[3] >= 200) sonarCount++;
      }
      // Map points first, then the live frame, then sonar-only surfaces, all in the viewer's Y-up axes.
      const liveCount = rows.length - mapCount - sonarCount;
      const points = new Float32Array(rows.length * 3), hits = new Uint16Array(rows.length);
      let m = 0, l = mapCount, s = mapCount + liveCount, hitSum = 0;
      for (const [x, y, z, strength] of rows) {
        const i = strength < 100 ? m++ : strength >= 200 ? s++ : l++;
        points.set([-y, z, -x], i * 3);
        if (strength < 100) { hits[i] = strength; hitSum += strength; }
      }
      const sonar = readSonarStatus(raw.frame.meta.sonar);
      const surface = points.subarray((mapCount + liveCount) * 3);
      const map = points.subarray(0, mapCount * 3), mapHits = hits.subarray(0, mapCount);
      let result = cached;
      if (!sameMap(cached, map, mapHits)) {
        if (pending && !sameMap(pending, map, mapHits)) return null;
        let job = pending;
        if (!job) {
          const baselineOptions = classifierSteps(pointSpacing(map));
          job = { points: map, hits: mapHits };
          pending = job;
          job.result = (async () => {
            let report;
            try {
              report = await classify(map, { hits: mapHits, baselineOptions });
              if (report.labels.length !== mapCount) throw new Error('Class count does not match the map');
            } catch {
              report = classifyRoom(map, { hits: mapHits, ...baselineOptions });
            }
            if (pending !== job) return null;
            analysis = report;
            cached = { points: map, hits: mapHits, report, colors: colorsFor(report.labels, mapCount) };
            pending = undefined;
            return cached;
          })();
        }
        result = await job.result;
        if (!result) return null;
      }
      const colors = new Float32Array(rows.length * 3);
      colors.set(result.colors);
      for (let i = mapCount; i < rows.length; i++) colors.set(i < mapCount + liveCount ? LIVE_COLOR : SONAR_COLOR, i * 3);
      const report = result.report;
      // Publish the overlay only for an accepted frame, never one skipped during inference.
      sonarSurface = surface;
      return { points, colors, hits, frame: raw.sequence, captureTime: raw.timestamp,
        snr: mapCount ? hitSum / mapCount : null,
        sonar: { delivery, acquisition, detectionCount: null },
        mapper: { mapPoints: mapCount, livePoints: liveCount, objects: report.objects.length,
          simulated: acquisition === 'simulated', analysis: report, floorArea: report.floorArea, roomHeight: report.roomHeight, sonar,
          delivery, acquisition, capture, stale: Boolean(capture && capture.state !== 'active' && rows.length),
          sonarSurface: surface } };
    },
  };
}
