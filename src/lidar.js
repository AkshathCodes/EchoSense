/**
 * LiDAR pathway: lidar_frame v1 from the bridge's /lidar/view endpoint.
 * Kept apart from src/sonar.js. See websocket-bridge/LIDAR_PROTOCOL.md.
 *
 * Coordinates: points arrive in ARKit world meters (+Y up) and are used as is.
 * The one viewer-only change is a vertical lift so the lowest retained point
 * sits on the viewer's y = 0 grid. ARKit puts y = 0 at the phone's starting
 * height, which would otherwise sink the room below the grid.
 */
import { createSpatialMemory, SURFACE } from './spatial-memory.js';
import { classifyRoom, colorsFor } from './room-classifier.js';

export const LIDAR_URL = 'ws://127.0.0.1:8765/lidar/view';
export const LIDAR_REPLAY_BYTES = 16_000_000;
const MAX_POINTS = 5000;
const trackingStates = ['normal', 'limited', 'not_available'];
const finite = n => typeof n === 'number' && Number.isFinite(n) && Math.abs(n) <= 1000;
const label = value => typeof value === 'string' && value.length > 0 && value.length <= 64 && !/\p{C}/u.test(value);

/** Validates a parsed lidar_frame v1. Throws on anything unexpected. */
export function readLidarFrame(raw) {
  if (raw?.type !== 'lidar_frame' || raw.schema_version !== 1) throw new Error('Unsupported LiDAR schema version');
  if (raw.coordinate_frame !== 'arkit_world' || raw.units !== 'meters') throw new Error('Unsupported LiDAR coordinates');
  if (!label(raw.session_id) || !label(raw.device_id) || !Number.isSafeInteger(raw.sequence) ||
      raw.sequence < 0 || !Number.isFinite(raw.timestamp) || !trackingStates.includes(raw.tracking) ||
      !['arkit_scene_depth', 'synthetic'].includes(raw.source)) throw new Error('Invalid LiDAR metadata');
  const pose = raw.camera_to_world;
  if (!Array.isArray(pose) || pose.length !== 16 || !pose.every(finite) ||
      pose[3] !== 0 || pose[7] !== 0 || pose[11] !== 0 || pose[15] !== 1) throw new Error('Invalid camera pose');
  const { points, confidences } = raw;
  if (!Array.isArray(points) || !Array.isArray(confidences) || points.length > MAX_POINTS ||
      points.length !== confidences.length) throw new Error('Invalid LiDAR point arrays');
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    if (!Array.isArray(p) || p.length !== 3 || !finite(p[0]) || !finite(p[1]) || !finite(p[2]) ||
        ![0, 1, 2].includes(confidences[i])) throw new Error('Invalid LiDAR point');
  }
  // Column-major 4x4: the translation column is the camera position in the world.
  return { sessionId: raw.session_id, deviceId: raw.device_id, sequence: raw.sequence, timestamp: raw.timestamp, tracking: raw.tracking,
    simulated: raw.source === 'synthetic', camera: [pose[12], pose[13], pose[14]], points, confidences };
}

export function lidarLabel({ mode, simulated }) {
  if (simulated == null) return mode === 'replay' ? 'LiDAR replay · waiting' : 'LiDAR · waiting';
  const kind = simulated ? 'Simulated LiDAR' : 'LiDAR';
  return mode === 'replay' ? `${kind} replay` : simulated ? kind : 'Live LiDAR';
}

/**
 * Holds one viewing session: decodes messages, feeds spatial memory, and
 * returns frames in the shape the scan viewer already consumes.
 * `onEvent(name)` fires for session_started, tracking_lost, tracking_restored,
 * publisher_connected and publisher_lost.
 */
export function createLidarSession({ memory = createSpatialMemory(), onEvent = () => {},
  now = () => performance.now(), classifyEvery = 1000 } = {}) {
  let sessionId = null, deviceId = null, tracking = null, paused = false, simulated = null;
  let link = { mode: 'live', publisher: false, recording: false };
  let path = [], pathRevision = -1, pathLift, pathMeters = 0;
  let cloud = new Float32Array(), cloudRevision = -1, cloudLift, estimatedFloor, hits = new Uint16Array();
  let sequence, timestamp, camera, lastSequence = -1, gap = false, breaks = new WeakSet();
  let colors = new Float32Array();
  let analysis = classifyRoom(new Float32Array()), analysedAt = -Infinity;

  /** Classify the same metric coordinates that the viewer and archive use. */
  function analyse(points = cloud, support = hits) {
    analysis = classifyRoom(points, { hits: support });
    analysedAt = now();
    return analysis;
  }

  function snapshot(includePoints) {
    const classify = includePoints && memory.revision !== cloudRevision &&
      (memory.count < 5000 || now() - analysedAt >= classifyEvery);
    if (classify) {
      hits = memory.hits();
      estimatedFloor = classifyRoom(memory.cloud(), { hits }).floorY;
    }
    const lift = -(estimatedFloor ?? memory.floor);
    if (memory.revision !== pathRevision || lift !== pathLift) {
      pathRevision = memory.revision;
      pathLift = lift;
      path = [];
      pathMeters = 0;
      for (const waypoint of memory.trajectory) {
        const [x, y, z] = waypoint;
        if (path.length && breaks.has(waypoint)) path.push(null);
        const prior = path.at(-1);
        if (prior) pathMeters += Math.hypot(x - prior[0], y + lift - prior[1], z - prior[2]);
        path.push([x, y + lift, z]);
      }
    }
    const scanner = camera ? [camera[0], camera[1] + lift, camera[2]] : null;
    const frame = { frame: sequence, captureTime: timestamp, lidar: { ...link, sessionId, deviceId,
      tracking, simulated, paused, scanner, path, stats: { ...memory.stats(), pathMeters } } };
    if (includePoints && (memory.revision !== cloudRevision || lift !== cloudLift)) {
      cloudRevision = memory.revision;
      cloud = memory.cloud(lift);
      hits = memory.hits();
      if (classify || lift !== cloudLift) analyse(cloud, hits);
      cloudLift = lift;
      // Points added since the last classification are drawn in the neutral colour.
      colors = colorsFor(analysis.labels.length > memory.count ? new Uint8Array() : analysis.labels, memory.count);
    }
    if (includePoints) Object.assign(frame, { points: cloud, colors, hits });
    return frame;
  }

  function clear() {
    memory.clear();
    camera = sequence = timestamp = undefined;
    gap = false;
    breaks = new WeakSet();
    estimatedFloor = undefined;
    analyse(new Float32Array(), new Uint16Array());
  }

  function newOrigin(id, device = null) {
    clear();
    sessionId = id;
    deviceId = device;
    tracking = simulated = null;
    lastSequence = -1;
  }

  return {
    memory, analyse,
    /** Latest room classification. See src/room-classifier.js. */
    get analysis() { return analysis; },
    get paused() { return paused; },
    setPaused(value) {
      if (paused && !value) gap = true;
      paused = Boolean(value);
    },
    clear,
    /** Forget everything, including which session was active. Call before a new connection. */
    reset() {
      newOrigin(null);
      paused = false;
      link = { mode: 'live', publisher: false, recording: false };
    },
    /** Current state as a viewer frame, for redrawing after Clear or Pause. */
    current() { return snapshot(true); },
    /**
     * Returns a viewer frame for LiDAR messages, or undefined when the payload
     * is not a LiDAR message so the caller can try the sonar decoder.
     */
    async decode(payload, includePoints = true) {
      if (payload instanceof Blob) payload = await payload.text();
      if (payload instanceof ArrayBuffer) payload = new TextDecoder().decode(payload);
      if (typeof payload !== 'string' || payload.length > 2_000_000) throw new Error('Invalid socket payload size');
      const raw = JSON.parse(payload);
      if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Expected an object');
      if (raw.type === 'lidar_status') {
        if (raw.schema_version !== 1 || !['live', 'replay'].includes(raw.mode) ||
            typeof raw.publisher_connected !== 'boolean' || typeof raw.recording !== 'boolean' ||
            !(raw.session_id === null || label(raw.session_id))) throw new Error('Invalid LiDAR status');
        const publisher = raw.publisher_connected;
        if (raw.mode === 'live' && publisher !== link.publisher) onEvent(publisher ? 'publisher_connected' : 'publisher_lost');
        link = { mode: raw.mode, publisher, recording: raw.recording };
        const changed = raw.session_id !== null && raw.session_id !== sessionId;
        if (changed) newOrigin(raw.session_id);
        if (raw.mode === 'live' && !publisher && !paused) {
          camera = undefined;
          gap = true;
        }
        return snapshot(includePoints && changed);
      }
      if (raw.type !== 'lidar_frame') return undefined;
      if (payload.length > 1_000_000) throw new Error('Invalid LiDAR frame size');
      const frame = readLidarFrame(raw);
      const changed = frame.sessionId !== sessionId || frame.deviceId !== deviceId || frame.simulated !== simulated;
      if (changed) {
        newOrigin(frame.sessionId, frame.deviceId);
        onEvent('session_started');
      }
      if (frame.sequence <= lastSequence) throw new Error('Sequence must increase within the LiDAR session');
      lastSequence = frame.sequence;
      if (tracking === 'normal' && frame.tracking !== 'normal') onEvent('tracking_lost');
      if (tracking !== null && tracking !== 'normal' && frame.tracking === 'normal') onEvent('tracking_restored');
      ({ tracking, simulated } = frame);
      if (!paused) {
        ({ sequence, timestamp } = frame);
        const previous = memory.trajectory.at(-1);
        memory.addFrame(frame);
        camera = frame.tracking === 'normal' ? frame.camera : undefined;
        const waypoint = memory.trajectory.at(-1);
        if (!camera) gap = true;
        else if (waypoint && waypoint !== previous) {
          if (gap && previous) breaks.add(waypoint);
          gap = false;
        }
      }
      return snapshot(includePoints && (!paused || changed));
    },
  };
}

/** Open a bridge recording locally and sample it into the existing replay timeline. */
export async function readLidarReplay(contents) {
  if (!contents.length || contents.length > LIDAR_REPLAY_BYTES) throw new Error('Choose a LiDAR JSONL recording up to 16 MB.');
  const lines = contents.trim().split(/\r?\n/).filter(line => line.trim());
  const stride = Math.max(1, Math.ceil(lines.length / 40));
  const session = createLidarSession({ classifyEvery: 0 }), history = [];
  let t = 0, previous, frame;
  await session.decode('{"type":"lidar_status","schema_version":1,"mode":"replay","publisher_connected":false,"session_id":null,"recording":false}');
  for (const [i, line] of lines.entries()) {
    const keep = i % stride === 0 || i === lines.length - 1;
    frame = await session.decode(line, keep);
    if (!frame || frame.captureTime === undefined) throw new Error(`Expected a LiDAR frame on line ${i + 1}.`);
    if (previous) {
      const sameOrigin = previous.lidar.sessionId === frame.lidar.sessionId && previous.lidar.deviceId === frame.lidar.deviceId;
      const delta = (frame.captureTime - previous.captureTime) * 1000;
      t += sameOrigin && delta > 0 && Number.isFinite(delta) ? delta : 1000 / 3;
    }
    if (keep) history.push({ ...frame, t });
    previous = frame;
  }
  if (!history.some(sample => sample.points.length)) throw new Error('This recording contains no retained surface points.');
  return { ...history.at(-1), history, source: frame.lidar.simulated ? 'mock' : 'live', space: null };
}

/**
 * Plan-view coverage map. Dark background is UNKNOWN: no measurement, no claim.
 * `trail` is the scanner path as [x, y, z] positions.
 */
export function drawCoverage(canvas, memory, path) {
  const ctx = canvas.getContext('2d'), { width, height } = canvas;
  ctx.fillStyle = '#070d13';
  ctx.fillRect(0, 0, width, height);
  let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
  memory.eachCell((x, z) => { x0 = Math.min(x0, x); x1 = Math.max(x1, x); z0 = Math.min(z0, z); z1 = Math.max(z1, z); });
  if (x0 === Infinity) return;
  const size = Math.max(1, Math.min((width - 12) / (x1 - x0 + 1), (height - 12) / (z1 - z0 + 1)));
  const left = (width - (x1 - x0 + 1) * size) / 2, top = (height - (z1 - z0 + 1) * size) / 2;
  memory.eachCell((x, z, state) => {
    ctx.fillStyle = state === SURFACE ? '#63d6f2' : '#1d4a5c';
    ctx.fillRect(left + (x - x0) * size, top + (z - z0) * size, Math.ceil(size), Math.ceil(size));
  });
  if (!path.length) return;
  const at = ([x, , z]) => [left + (x / memory.cell - x0) * size, top + (z / memory.cell - z0) * size];
  ctx.strokeStyle = '#f79c38';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  path.forEach((p, i) => {
    if (p) (path[i - 1] ? ctx.lineTo : ctx.moveTo).call(ctx, ...at(p));
  });
  ctx.stroke();
  ctx.fillStyle = '#ffd08a';
  ctx.beginPath();
  ctx.arc(...at(path.at(-1)), 3, 0, Math.PI * 2);
  ctx.fill();
}
