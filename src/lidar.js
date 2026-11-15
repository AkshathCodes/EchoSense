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
const MAX_POINTS = 5000;
const trackingStates = ['normal', 'limited', 'not_available'];
const finite = n => typeof n === 'number' && Number.isFinite(n) && Math.abs(n) <= 1000;

/** Validates a parsed lidar_frame v1. Throws on anything unexpected. */
export function readLidarFrame(raw) {
  if (raw.schema_version !== 1) throw new Error('Unsupported LiDAR schema version');
  if (raw.coordinate_frame !== 'arkit_world' || raw.units !== 'meters') throw new Error('Unsupported LiDAR coordinates');
  if (typeof raw.session_id !== 'string' || !raw.session_id || !Number.isSafeInteger(raw.sequence) ||
      raw.sequence < 0 || !Number.isFinite(raw.timestamp) || !trackingStates.includes(raw.tracking) ||
      !['arkit_scene_depth', 'synthetic'].includes(raw.source)) throw new Error('Invalid LiDAR metadata');
  const pose = raw.camera_to_world;
  if (!Array.isArray(pose) || pose.length !== 16 || !pose.every(finite)) throw new Error('Invalid camera pose');
  const { points, confidences } = raw;
  if (!Array.isArray(points) || !Array.isArray(confidences) || points.length > MAX_POINTS ||
      points.length !== confidences.length) throw new Error('Invalid LiDAR point arrays');
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    if (!Array.isArray(p) || p.length !== 3 || !finite(p[0]) || !finite(p[1]) || !finite(p[2]) ||
        ![0, 1, 2].includes(confidences[i])) throw new Error('Invalid LiDAR point');
  }
  // Column-major 4x4: the translation column is the camera position in the world.
  return { sessionId: raw.session_id, sequence: raw.sequence, timestamp: raw.timestamp, tracking: raw.tracking,
    simulated: raw.source === 'synthetic', camera: [pose[12], pose[13], pose[14]], points, confidences };
}

export function lidarLabel({ mode, simulated }) {
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
  let sessionId = null, tracking = null, paused = false, simulated = false;
  let link = { mode: 'live', publisher: false, recording: false };
  let trail = [], trailRevision = -1, cloud = new Float32Array(), cloudRevision = -1, sequence, timestamp, camera;
  let analysis = classifyRoom(new Float32Array()), analysedAt = -Infinity;

  /** Runs the room classifier on everything retained so far, in ARKit coordinates. */
  function analyse() {
    analysis = classifyRoom(memory.cloud(), { hits: memory.hits() });
    analysedAt = now();
    return analysis;
  }

  function snapshot(includePoints) {
    // The classifier's floor ignores stray returns; the raw minimum is the fallback.
    const lift = -(analysis.floorY ?? memory.floor);
    if (memory.revision !== trailRevision) {
      trailRevision = memory.revision;
      // The viewer joins trail samples less than 1.5 s apart. Spacing here is nominal.
      trail = memory.trajectory.map(([x, y, z], i) => ({ t: i * 1000, target: { position: [x, y + lift, z] } }));
    }
    const frame = { lidar: { ...link, sessionId, tracking, simulated, paused, trail, stats: memory.stats() } };
    if (sequence !== undefined) Object.assign(frame, { frame: sequence, captureTime: timestamp });
    if (camera) frame.target = { position: [camera[0], camera[1] + lift, camera[2]], confidence: 1 };
    if (includePoints && memory.revision !== cloudRevision) {
      cloudRevision = memory.revision;
      // Classifying every frame is wasted work once the map is large.
      if (memory.count < 5000 || now() - analysedAt >= classifyEvery) analyse();
      cloud = memory.cloud(lift);
      // Points added since the last classification are drawn in the neutral colour.
      cloud.classColors = colorsFor(analysis.labels.length > memory.count ? new Uint8Array() : analysis.labels, memory.count);
    }
    if (includePoints) frame.points = cloud;
    return frame;
  }

  return {
    memory, analyse,
    /** Latest room classification. See src/room-classifier.js. */
    get analysis() { return analysis; },
    get paused() { return paused; },
    setPaused(value) { paused = Boolean(value); },
    clear() {
      memory.clear();
      camera = undefined;
      analyse();
    },
    /** Forget everything, including which session was active. Call before a new connection. */
    reset() {
      memory.clear();
      analyse();
      sessionId = tracking = null;
      camera = sequence = timestamp = undefined;
      link = { mode: 'live', publisher: false, recording: false };
    },
    /** Current state as a viewer frame, for redrawing after Clear or Pause. */
    current() { return snapshot(true); },
    /**
     * Returns a viewer frame for LiDAR messages, or undefined when the payload
     * is not a LiDAR message so the caller can try the sonar decoder.
     */
    async decode(payload) {
      if (payload instanceof Blob) payload = await payload.text();
      if (payload instanceof ArrayBuffer) payload = new TextDecoder().decode(payload);
      if (typeof payload !== 'string' || payload.length > 1_000_000) throw new Error('Invalid socket payload size');
      const raw = JSON.parse(payload);
      if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Expected an object');
      if (raw.type === 'lidar_status') {
        const publisher = Boolean(raw.publisher_connected);
        if (raw.mode === 'live' && publisher !== link.publisher) onEvent(publisher ? 'publisher_connected' : 'publisher_lost');
        link = { mode: raw.mode === 'replay' ? 'replay' : 'live', publisher, recording: Boolean(raw.recording) };
        return snapshot(false);
      }
      if (raw.type !== 'lidar_frame') return undefined;
      const frame = readLidarFrame(raw);
      if (frame.sessionId !== sessionId) {
        // A new ARKit origin: earlier geometry is in a different coordinate frame.
        sessionId = frame.sessionId;
        memory.clear();
        analyse();
        tracking = null;
        onEvent('session_started');
      }
      if (tracking === 'normal' && frame.tracking !== 'normal') onEvent('tracking_lost');
      if (tracking !== null && tracking !== 'normal' && frame.tracking === 'normal') onEvent('tracking_restored');
      ({ tracking, simulated, sequence, timestamp } = frame);
      if (!paused) {
        memory.addFrame(frame);
        if (frame.tracking === 'normal') camera = frame.camera;
      }
      return snapshot(!paused);
    },
  };
}

/**
 * Plan-view coverage map. Dark background is UNKNOWN: no measurement, no claim.
 * `trail` is the scanner path as [x, y, z] positions.
 */
export function drawCoverage(canvas, memory) {
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
  const path = memory.trajectory;
  if (!path.length) return;
  const at = ([x, , z]) => [left + (x / memory.cell - x0) * size, top + (z / memory.cell - z0) * size];
  ctx.strokeStyle = '#f79c38';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  path.forEach((p, i) => i ? ctx.lineTo(...at(p)) : ctx.moveTo(...at(p)));
  ctx.stroke();
  ctx.fillStyle = '#ffd08a';
  ctx.beginPath();
  ctx.arc(...at(path.at(-1)), 3, 0, Math.PI * 2);
  ctx.fill();
}
