import { readPreview } from './feed.js';

export const SONAR_URL = 'ws://127.0.0.1:8765/ws';
const sourceKinds = ['simulated', 'recorded', 'live'];
const coordinates = values => values.every(n => Number.isFinite(n) && Math.abs(n) <= 10000);
// Forward points toward -Z in the viewer; left points toward -X; up is +Y.
const toViewer = ([forward, left, up]) => [-left, up, -forward];

export function sonarLabel({ delivery, acquisition }) {
  if (delivery === 'recorded') return acquisition === 'simulated' ? 'Sonar replay · simulated' : 'Sonar replay';
  return acquisition === 'simulated' || delivery === 'simulated' ? 'Simulated sonar' : 'Live sonar';
}

export async function decodeSocketFrame(payload) {
  if (payload instanceof Blob) payload = await payload.text();
  if (payload instanceof ArrayBuffer) payload = new TextDecoder().decode(payload);
  if (typeof payload !== 'string' || payload.length > 2_000_000) throw new Error('Invalid socket payload size');
  const raw = JSON.parse(payload);
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Expected an object');
  if (raw.type !== 'sonar_frame' && !Object.hasOwn(raw, 'protocol_version')) return readPreview(payload);
  if (raw.protocol_version !== '0.1' || raw.type !== 'sonar_frame' || raw.frame?.format_version !== '0.2') {
    throw new Error('Unsupported sonar frame version');
  }
  const { sequence, timestamp, source: delivery, acquisition_source: acquisition, detections: document } = raw;
  if (!Number.isSafeInteger(sequence) || sequence < 0 || !Number.isFinite(timestamp) ||
      !sourceKinds.includes(delivery) || !sourceKinds.includes(acquisition)) {
    throw new Error('Invalid sonar metadata');
  }
  const rows = raw.frame.points;
  if (!Array.isArray(rows) || rows.length > 20000) throw new Error('Invalid point count');
  const points = new Float32Array(rows.length * 3);
  let snr = 0;
  for (const [i, row] of rows.entries()) {
    if (!Array.isArray(row) || row.length !== 4 || !coordinates(row.slice(0, 3)) ||
        !Number.isFinite(row[3]) || row[3] < 0) throw new Error('Invalid sonar point');
    points.set(toViewer(row), i * 3);
    snr += row[3] / rows.length;
  }
  let target = null;
  if (document !== null) {
    if (document?.format_version !== '0.1' || !Array.isArray(document.detections) ||
        document.detections.length > 256) throw new Error('Invalid detections document');
    for (const detection of document.detections) {
      if (!detection || typeof detection !== 'object') throw new Error('Invalid detection');
      if (detection.class !== 'person') continue;
      const { centroid, confidence } = detection;
      if (!Array.isArray(centroid) || centroid.length !== 3 || !coordinates(centroid) ||
          !Number.isFinite(confidence) || confidence < 0 || confidence > 1) throw new Error('Invalid person detection');
      if (!target || confidence > target.confidence) target = { position: toViewer(centroid), confidence };
    }
  }
  return { points, target, frame: sequence, captureTime: timestamp, snr: rows.length ? snr : null,
    sonar: { delivery, acquisition, detectionCount: document?.detections.length ?? null } };
}
