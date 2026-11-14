/**
 * Frontend-owned demonstration decoder. Replace this with the backend team's
 * decoder once the wire format is agreed. The transport never inspects a frame.
 */
const limit = 100000;
const xyz = value => Array.isArray(value) && value.length === 3 &&
  value.every(n => Number.isFinite(n) && Math.abs(n) <= 10000);
const owns = (obj, key) => Object.hasOwn(obj, key);

export async function decodePreview(payload) {
  if (payload instanceof Blob) payload = await payload.text();
  if (payload instanceof ArrayBuffer) payload = new TextDecoder().decode(payload);
  return readPreview(payload);
}

export function readPreview(payload) {
  const raw = JSON.parse(payload);
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Expected an object');
  const frame = {};
  if (owns(raw, 'points')) {
    if (!Array.isArray(raw.points) || raw.points.length > limit || !raw.points.every(xyz)) {
      throw new Error('Expected up to 100,000 finite XYZ positions');
    }
    frame.points = new Float32Array(raw.points.length * 3);
    raw.points.forEach((p, i) => frame.points.set(p, i * 3));
  }
  if (owns(raw, 'frame')) {
    if (!Number.isSafeInteger(raw.frame) || raw.frame < 0) throw new Error('Invalid frame number');
    frame.frame = raw.frame;
  }
  if (owns(raw, 'latencyMs')) {
    if (!Number.isFinite(raw.latencyMs) || raw.latencyMs < 0) throw new Error('Invalid latency');
    frame.latencyMs = raw.latencyMs;
  }
  if (owns(raw, 'target')) {
    const target = raw.target;
    if (target !== null && (!xyz(target?.position) || !Number.isFinite(target.confidence) ||
      target.confidence < 0 || target.confidence > 1)) throw new Error('Invalid position estimate');
    frame.target = target;
  }
  if (!Object.keys(frame).length) throw new Error('No supported fields in message');
  return frame;
}

export function openFeed(address, { decode, onFrame, onStatus, onInvalid = () => {},
  transport = url => new WebSocket(url) }) {
  const url = new URL(address);
  if (!['ws:', 'wss:'].includes(url.protocol)) throw new Error('Use a ws:// or wss:// address.');
  const socket = transport(url.href);
  let active = true, sequence = 0, applied = 0;
  onStatus('connecting');
  socket.addEventListener('open', () => { if (active) onStatus('connected'); });
  socket.addEventListener('close', () => {
    if (!active) return;
    active = false;
    onStatus('disconnected');
  });
  socket.addEventListener('error', () => {
    if (!active) return;
    active = false;
    socket.close();
    onStatus('error');
  });
  socket.addEventListener('message', async event => {
    if (!active) return;
    const id = ++sequence;
    try {
      const frame = await decode(event.data);
      if (active && id > applied) {
        applied = id;
        onFrame(frame);
      }
    } catch (error) {
      if (active) onInvalid(error);
    }
  });
  return () => {
    if (!active) return;
    active = false;
    socket.close();
    onStatus('disconnected');
  };
}
