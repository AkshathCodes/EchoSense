// Decoder for the existing lidar-pivot relay. Keep wire conversion here so the
// viewer and spatial memory can also consume native ARKit world coordinates.
export const LIDAR_REPLAY_BYTES = 16_000_000;
const kinds = ['live', 'recorded', 'simulated'];
const trackingStates = ['normal', 'limited', 'not_available'];

export function lidarLabel({ acquisition, delivery }) {
  if (acquisition === 'simulated') {
    return delivery === 'recorded' ? 'Synthetic LiDAR replay' : 'Synthetic LiDAR · controlled demo';
  }
  if (acquisition === 'unverified') return delivery === 'recorded' ? 'LiDAR replay · unverified' : 'LiDAR relay · unverified';
  return delivery === 'recorded' ? 'LiDAR replay' : 'Live LiDAR';
}

export async function decodeRelayLidar(payload) {
  if (payload instanceof Blob) payload = await payload.text();
  if (payload instanceof ArrayBuffer) payload = new TextDecoder().decode(payload);
  if (typeof payload !== 'string' || payload.length > 2_000_000) throw new Error('Invalid LiDAR message size');
  const raw = JSON.parse(payload);
  const frame = raw?.frame, meta = frame?.meta;
  if (raw?.type !== 'sonar_frame' || raw.protocol_version !== '0.1' || frame?.format_version !== '0.2' ||
      meta?.modality !== 'lidar' || raw.detections !== null) throw new Error('Unsupported LiDAR relay envelope');
  if (!Number.isSafeInteger(raw.sequence) || raw.sequence < 0 || !Number.isFinite(raw.timestamp) ||
      !kinds.includes(raw.source) || !kinds.includes(raw.acquisition_source) ||
      !['sensor', 'world'].includes(meta.reference) || !trackingStates.includes(meta.tracking) ||
      typeof meta.sensor_id !== 'string' || !meta.sensor_id) throw new Error('Invalid LiDAR metadata');
  const rows = frame.points;
  if (!Array.isArray(rows) || rows.length > 20_000) throw new Error('Invalid LiDAR point count');
  const points = new Float32Array(rows.length * 3);
  let sum = 0;
  for (const [i, row] of rows.entries()) {
    if (!Array.isArray(row) || row.length !== 4 ||
        !row.slice(0, 3).every(value => Number.isFinite(value) && Math.abs(value) <= 10_000) ||
        ![0, 1, 2].includes(row[3])) throw new Error('Invalid LiDAR point');
    // Relay 0.1 packs [forward,left,up,confidence]. The viewer uses right,
    // up and back. Native ARKit world XYZ would enter the viewer unchanged.
    points.set([-row[1], row[2], -row[0]], i * 3);
    sum += row[3];
  }
  const synthetic = /^FAKE-/i.test(meta.sensor_id) || raw.acquisition_source === 'simulated' || raw.source === 'simulated';
  const acquisition = synthetic ? 'simulated' : meta.sensor_id === 'iphone-lidar' ? raw.acquisition_source : 'unverified';
  return { points, frame: raw.sequence, captureTime: raw.timestamp, lidar: {
    acquisition, delivery: raw.source, reference: meta.reference, tracking: meta.tracking,
    deviceId: meta.sensor_id, depthConfidence: rows.length ? sum / rows.length : null,
  } };
}

export function createLidarMap(pointLimit = 40_000) {
  const voxels = new Map(), path = [];
  let session, observed, sequence = -1;
  function clear() {
    voxels.clear();
    path.length = 0;
    session = observed = undefined;
    sequence = -1;
  }
  return {
    clear,
    observe(frame) {
      const { lidar, points } = frame;
      // Without an explicit origin ID, even world frames are only snapshots:
      // the phone can reset its map without telling the relay.
      const key = lidar.reference === 'world' && lidar.sessionId
        ? JSON.stringify([lidar.deviceId, lidar.sessionId, lidar.acquisition]) : null;
      if (key !== session) { clear(); session = key; }
      if (frame.frame <= sequence) return null;
      sequence = frame.frame;
      if (!key) return { ...frame, lidar: { ...lidar, path: [] } };
      let scanner = null;
      if (lidar.tracking === 'normal') {
        for (let i = 0; i < points.length; i += 3) {
          const k = `${Math.floor(points[i] / 0.06)},${Math.floor(points[i + 1] / 0.06)},${Math.floor(points[i + 2] / 0.06)}`;
          if (voxels.has(k)) continue;
          voxels.set(k, [points[i], points[i + 1], points[i + 2]]);
          if (voxels.size > pointLimit) voxels.delete(voxels.keys().next().value);
        }
        observed = new Float32Array(voxels.size * 3);
        let i = 0;
        for (const xyz of voxels.values()) { observed.set(xyz, i); i += 3; }
        scanner = lidar.scanner ?? null;
      }
      const last = path.at(-1);
      if (scanner ? !last || Math.hypot(...scanner.map((n, i) => n - last[i])) >= 0.03 : last) {
        path.push(scanner);
        if (path.length > 480) path.shift();
      }
      return { ...frame, points: observed ?? new Float32Array(), lidar: { ...lidar, scanner, path: [...path] } };
    },
  };
}

// A local playback file contains captured browser envelopes, one per line.
// Reuse Saved Maps' timeline instead of implementing another replay transport.
export async function readLidarReplay(contents) {
  if (!contents.length || contents.length > LIDAR_REPLAY_BYTES) throw new Error('Choose a LiDAR JSONL file up to 16 MB.');
  const history = [], map = createLidarMap();
  let first, last;
  for (const line of contents.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const frame = await decodeRelayLidar(line);
    first ??= frame.captureTime;
    if (last && (frame.captureTime < last.captureTime || frame.frame <= last.frame ||
        frame.lidar.deviceId !== last.lidar.deviceId || frame.lidar.acquisition !== last.lidar.acquisition)) {
      throw new Error('Choose an ordered LiDAR recording from one source.');
    }
    frame.lidar.delivery = 'recorded';
    const t = (frame.captureTime - first) * 1000;
    last = { ...map.observe(frame), t };
    if (history.length && t - history.at(-1).t < 250) continue;
    history.push(last);
    // Preserve the full span of longer recordings without an unbounded history.
    if (history.length > 120) history.splice(1, 1);
  }
  if (!last?.points.length && !history.some(frame => frame.points.length)) throw new Error('No LiDAR observations to replay.');
  if (history.at(-1) !== last) {
    if (history.at(-1).t === last.t) history.pop();
    history.push(last);
  }
  return { ...last, history, source: last.lidar.acquisition === 'live' ? 'live' : 'mock', space: null };
}
