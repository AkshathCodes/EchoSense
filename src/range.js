/** Independent range readout; never creates geometry or changes LiDAR coordinates. */
import { openFeed } from './feed.js';
const finite = n => typeof n === 'number' && Number.isFinite(n);
const id = s => typeof s === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(s);
export function decodeRange(payload) {
  if (typeof payload !== 'string' || payload.length > 16384) throw new Error('Invalid range payload');
  const value = JSON.parse(payload);
  if (value?.type === 'range_status' && value.schema_version === 1 &&
      ['live','replay'].includes(value.mode) && typeof value.publisher_connected === 'boolean' && typeof value.recording === 'boolean') return { rangeStatus: value };
  if (value?.type !== 'range_update' || value.schema_version !== 1 || !['live','manual','synthetic','replay'].includes(value.delivery)) throw new Error('Unsupported range update');
  const o = value.observation, s = value.statistics;
  if (o?.type !== 'range_observation' || o.schema_version !== 1 || !id(o.sensor_id) || !id(o.session_id) ||
      typeof o.sensor_model !== 'string' || !o.sensor_model.length ||
      !Number.isSafeInteger(o.sequence) || o.sequence < 0 || !Number.isSafeInteger(o.capture_timestamp) ||
      !['unix_ms','device_monotonic_ms','host_receive_unix_ms'].includes(o.timestamp_basis) ||
      !['hardware','manual','synthetic'].includes(o.source) ||
      !['valid','timeout','no_return','invalid','disconnected'].includes(o.status) ||
      typeof o.valid !== 'boolean' || o.valid !== (o.status === 'valid') || o.timed_out !== (o.status === 'timeout') ||
      (o.valid ? !finite(o.distance_m) || o.distance_m <= 0 : o.distance_m !== null)) throw new Error('Invalid range observation');
  const expected = {hardware:'live',manual:'manual',synthetic:'synthetic'}[o.source];
  if (value.delivery !== 'replay' && value.delivery !== expected) throw new Error('Range provenance mismatch');
  if (o.source === 'synthetic' && (!o.sensor_id.startsWith('synthetic-') || !o.session_id.startsWith('synthetic-'))) throw new Error('Unlabeled synthetic range');
  if (!s || typeof s.available !== 'boolean' || !Number.isInteger(s.sample_count) || s.sample_count < 1 || s.sample_count > 101 ||
      ['valid_count','missing_count','invalid_count','outlier_count'].some(k => !Number.isInteger(s[k]) || s[k] < 0 || s[k] > s.sample_count) ||
      ['median_m','spread_m','raw_spread_m','reference_m','absolute_error_m'].some(k => s[k] !== null && (!finite(s[k]) || s[k] < 0)) ||
      (s.available ? s.median_m === null : s.median_m !== null)) throw new Error('Invalid range statistics');
  return { range: value };
}

export function rangeLabel(update) {
  const source = {hardware:'Hardware',manual:'Manual',synthetic:'SYNTHETIC'}[update.observation.source];
  return update.delivery === 'replay' ? `REPLAY · ${source}` : source;
}

export function createRangeState({ maxSensors = 32, historySize = 20 } = {}) {
  if (!Number.isInteger(maxSensors) || maxSensors < 1 || maxSensors > 32 || !Number.isInteger(historySize) || historySize < 1 || historySize > 101) throw new Error('Invalid range history bounds');
  const sensors = new Map();
  return {
    accept(update) {
      const o = update.observation, old = sensors.get(o.sensor_id);
      if (!old && sensors.size >= maxSensors) throw new Error('Range sensor cap');
      const same = old?.update.observation.session_id === o.session_id && old?.update.delivery === update.delivery;
      if (same && o.sequence <= old.update.observation.sequence) return false;
      const history = same ? old.history.slice() : [];
      history.push({sequence:o.sequence,distance_m:o.distance_m,status:o.status,capture_timestamp:o.capture_timestamp,timestamp_basis:o.timestamp_basis});
      if (history.length > historySize) history.shift();
      sensors.set(o.sensor_id, { update, history });
      return true;
    },
    values: () => [...sensors.values()],
    clear: () => sensors.clear(),
  };
}

/** Akshath's narrow hook: mountRangePanel(container, {url}); no WebGL changes. */
export function mountRangePanel(root, { url = 'ws://127.0.0.1:8765/range/view', transport } = {}) {
  const doc = root.ownerDocument, state = createRangeState();
  const status = doc.createElement('p'), rows = doc.createElement('section');
  status.textContent = 'Range disconnected'; root.replaceChildren(status, rows);
  let stop;
  function render() {
    rows.replaceChildren();
    for (const {update, history} of state.values()) {
      const o = update.observation, s = update.statistics, card = doc.createElement('article');
      const title = doc.createElement('h2'); title.textContent = `${o.sensor_id} · ${rangeLabel(update)}`;
      const reading = doc.createElement('strong'); reading.textContent = o.valid ? `${o.distance_m.toFixed(3)} m` : `Unavailable: ${o.status}`;
      const detail = doc.createElement('p'); detail.textContent = `${o.sensor_model} · calibration ${o.calibration_status} · median ${s.available ? s.median_m.toFixed(3)+' m' : 'withheld'} · spread ${s.spread_m === null ? 'n/a' : s.spread_m.toFixed(3)+' m'} · misses ${s.missing_count}/${s.sample_count} · outliers ${s.outlier_count}`;
      const clock = doc.createElement('p'); clock.textContent = `Timestamp ${o.capture_timestamp} (${o.timestamp_basis}); sequence ${o.sequence}`;
      const recent = doc.createElement('p'); recent.textContent = 'Recent: '+history.map(h => h.distance_m === null ? h.status : h.distance_m.toFixed(3)+' m').join(' | ');
      card.append(title, reading, detail, clock, recent); rows.append(card);
    }
  }
  return {
    connect() {
      stop?.(); state.clear(); render();
      stop = openFeed(url, {transport, decode:decodeRange,
        onStatus: value => {status.textContent = `Range ${value}`;},
        onInvalid: () => {status.textContent = 'Malformed range message rejected';},
        onFrame: frame => {
          if (frame.rangeStatus) {status.textContent = `${frame.rangeStatus.mode} · adapter ${frame.rangeStatus.publisher_connected ? 'connected' : 'disconnected'}`; return;}
          if (state.accept(frame.range)) render();
        }});
    },
    disconnect() {stop?.(); stop=undefined;},
  };
}
