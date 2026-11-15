import { buildRoom, anchors } from './room.js';
import { createViewer } from './viewer.js';
import { mockFrame } from './mock.js';
import { openFeed } from './feed.js';
import { decodeSocketFrame, sonarLabel, SONAR_URL } from './sonar.js';
import { createLidarMap, decodeRelayLidar, lidarLabel, LIDAR_REPLAY_BYTES, readLidarReplay } from './lidar.js';
import { openArchive, positions, sampleHistory, thumbnail } from './archive.js';
import { sampleScans, MOCK_SPACE } from './samples.js';
import { createLibrary } from './library.js';
import { createReplay } from './replay.js';

const el = id => document.getElementById(id);
const canvas = el('reconstruction');
const mode = el('render-mode'), pointSize = el('point-size'), pointCap = el('max-vertices');
const skip = el('frame-skip'), grid = el('grid'), rings = el('rings');
const connection = el('connection-state'), note = el('connection-note'), source = el('source');
const address = el('address'), connect = el('connect');
const feedMode = el('feed-mode'), lidarPause = el('lidar-pause'), lidarClear = el('lidar-clear');
address.value = SONAR_URL;
const marker = el('target-marker'), loading = el('loading');
const labels = anchors.map((_, i) => {
  const label = document.createElement('span');
  label.className = 'anchor-label';
  label.textContent = `● RF ${i + 1}`;
  el('anchor-labels').append(label);
  return label;
});
const viewLabels = { orbit: 'Perspective view', camera: 'In camera mode', top: 'Top-down view' };
const views = [...document.querySelectorAll('[data-view]')].filter(node => node.tagName === 'BUTTON');
const numbers = new Intl.NumberFormat('en-US');
const motion = matchMedia('(prefers-reduced-motion: reduce)');
let viewer, view = 'orbit', live = false, disconnect;
let latest = {}, pendingCloud, frameNumber = 0, lastTick = -1, lastTelemetry = -1;
let userChangedPanel = false;
const replay = createReplay();
let workspace = 'scan', savedMap, livePoints, currentPoints, demoPoints, latestTargetAt, scanSettings;
let activeSample, renderOptions, lastHud = -1, sliceBounds = [0, 3.2], frameSonar = false;
let scanCameraBeforeSonar;
let sonarReplayComplete = false, skippedSonar;
const emptyPoints = new Float32Array();
const unsetPoints = Symbol('reset geometry');
const history = [];
const library = createLibrary({ show, open: openSaved, scan: returnToScan });
const lidarMap = createLidarMap();
let lidarSample, lidarPaused = false, lidarFrameFit = false, lidarSeenAt;
const lidarSelected = () => feedMode.value === 'lidar';
const scanLabel = map => map.lidar ? lidarLabel(map.lidar) : map.sonar ? sonarLabel(map.sonar)
  : map.source === 'mock' ? 'Mock' : 'Live';

function updateLidarControls() {
  el('feed-mode-row').hidden = Boolean(savedMap);
  el('lidar-controls').hidden = Boolean(savedMap) || !lidarSelected();
  lidarPause.disabled = !disconnect || (!lidarSample && !lidarPaused);
  lidarClear.disabled = !lidarSample;
  lidarPause.textContent = lidarPaused ? 'Resume display' : 'Pause display';
}

function clearLidar(hold = false) {
  lidarMap.clear();
  lidarSample = undefined;
  lidarSeenAt = undefined;
  lidarFrameFit = true;
  lidarPaused = hold;
  history.length = 0;
  updateLidarControls();
}

function updateModeAvailability() {
  const external = Boolean(savedMap) || live || lidarSelected();
  mode.querySelector('[value="mesh"]').disabled = external;
  rings.disabled = external;
  skip.disabled = Boolean(savedMap?.lidar || lidarSelected());
  if (external && mode.value === 'mesh') mode.value = 'points';
  el('mesh-tint').disabled = external;
  setMode();
}

function show(name) {
  if (workspace === 'compare') library.endCompare();
  if (name !== 'scan') replay.pause();
  workspace = name;
  historyReplace(name === 'scan' && !savedMap ? '' : '#maps');
  source.hidden = name !== 'scan';
  for (const view of ['scan', 'library', 'compare']) {
    el(view + '-stage').hidden = name !== view;
    el(view + '-footer').hidden = name !== view;
  }
  for (const tab of ['scan', 'library']) {
    const current = tab === name || tab === 'library' && (name === 'compare' || savedMap);
    if (current && !(tab === 'scan' && savedMap)) el(tab + '-nav').setAttribute('aria-current', 'page');
    else el(tab + '-nav').removeAttribute('aria-current');
  }
  if (name !== 'scan') el(name === 'library' ? 'library-title' : 'compare-title').focus();
}

function historyReplace(hash) {
  const url = new URL(location.href);
  if (url.hash === hash) return;
  url.hash = hash;
  window.history.replaceState(null, '', url);
}

function openSaved(map) {
  if (!viewer) return;
  if (!savedMap) scanSettings = {
    camera: viewer.camera(), mode: mode.value, slice: el('slice-height').value,
  };
  savedMap = map;
  currentPoints = unsetPoints;
  activeSavedMap = undefined;
  replay.open(map);
  el('replay').hidden = false;
  el('scan-capture').hidden = true;
  el('connection-form').hidden = true;
  el('connection-note').hidden = true;
  updateLidarControls();
  updateModeAvailability();
  writeSource(map.lidar?.delivery === 'recorded' ? scanLabel(map) : `Saved · ${scanLabel(map)}`);
  source.removeAttribute('data-live');
  set('study', map.name);
  show('scan');
  el('back-library').focus();
}

function returnToScan() {
  if (savedMap) {
    replay.pause();
    savedMap = undefined;
    currentPoints = unsetPoints;
    el('replay').hidden = true;
    el('scan-capture').hidden = false;
    el('connection-form').hidden = false;
    el('connection-note').hidden = false;
    updateLidarControls();
    mode.value = scanSettings.mode;
    const { state, view: previousView } = scanSettings.camera;
    view = previousView;
    viewer.follow(state, view);
    updateViewLabel();
    updateModeAvailability();
    configureSlice(lidarSelected() ? lidarSample?.points ?? emptyPoints : live ? livePoints ?? emptyPoints : demoPoints);
    el('slice-height').value = scanSettings.slice;
    updateSliceLabel();
    showScanSource();
  }
  show('scan');
}

el('scan-nav').addEventListener('click', returnToScan);
el('library-nav').addEventListener('click', () => show('library'));
el('back-library').addEventListener('click', () => show('library'));
el('slice-enabled').addEventListener('change', event => {
  el('slice-row').hidden = !event.target.checked;
  updateSliceLabel();
});
const updateSliceLabel = () => set('slice-value', `${Number(el('slice-height').value).toFixed(1)} m`);
el('slice-height').addEventListener('input', updateSliceLabel);

function set(id, value) {
  const node = el(id);
  if (node.textContent !== String(value)) node.textContent = value;
}

function setPanel(open) {
  el('control-body').hidden = !open;
  el('collapse').textContent = open ? '−' : '+';
  el('collapse').setAttribute('aria-expanded', String(open));
  el('collapse').setAttribute('aria-label', `${open ? 'Collapse' : 'Expand'} scan controls`);
}
const mobile = matchMedia('(max-width: 650px)');
setPanel(!mobile.matches);
mobile.addEventListener('change', e => { if (!userChangedPanel) setPanel(!e.matches); });
el('collapse').addEventListener('click', () => {
  userChangedPanel = true;
  setPanel(el('control-body').hidden);
});

function setMode() {
  el('tint-row').hidden = mode.value !== 'mesh';
}
mode.addEventListener('change', setMode);
pointSize.addEventListener('input', () => set('size-output', pointSize.value));
skip.addEventListener('change', () => {
  skip.value = Math.min(30, Math.max(0, Math.trunc(Number(skip.value) || 0)));
});
function updateViewLabel() {
  for (const button of views) button.setAttribute('aria-pressed', String(button.dataset.view === view));
  set('view-label', viewLabels[view]);
}
function resetScanCamera() {
  viewer?.preset(view);
  if ((savedMap?.sonar || savedMap?.lidar || !savedMap && (lidarSelected() || latest.sonar)) && currentPoints instanceof Float32Array) {
    viewer.frameCloud(currentPoints);
  }
}
for (const button of views) button.addEventListener('click', () => {
  view = button.dataset.view;
  resetScanCamera();
  updateViewLabel();
});
el('zoom-in').addEventListener('click', () => viewer?.zoom(0.82));
el('zoom-out').addEventListener('click', () => viewer?.zoom(1.22));
el('reset-view').addEventListener('click', resetScanCamera);

function writeSource(label) {
  if (source.textContent === label) return;
  source.replaceChildren(document.createElement('i'), document.createTextNode(label));
}

function showScanSource() {
  if (lidarSelected()) {
    const lidar = lidarSample?.lidar;
    source.toggleAttribute('data-live', Boolean(disconnect && lidar?.acquisition === 'live'));
    writeSource(lidar ? lidarLabel(lidar) : 'LiDAR · No observations');
    set('study', lidar?.reference === 'world' ? 'LiDAR / Room observations'
      : lidar ? 'LiDAR / Phone-relative view' : 'LiDAR / Exploration map');
    return;
  }
  const sonar = latest.sonar;
  source.toggleAttribute('data-live', live && sonar?.acquisition !== 'simulated');
  writeSource(!live ? 'Mock data' : sonar ? sonarLabel(sonar) : 'Socket data');
  set('study', !live ? 'Living room / sample scan'
    : sonar?.modality === 'lidar' ? sonar.reference === 'world' ? 'LiDAR · Room map' : 'LiDAR · Phone-relative scan'
    : sonar ? 'Sonar · Sensor-relative scan' : 'Incoming room scan');
}

function applyFrame(frame, force = false) {
  const { points, ...telemetry } = frame;
  const usePoints = points && (force || !points.length || frameNumber++ % (Number(skip.value) + 1) === 0);
  // A sonar detection is relative to its own frame. Skip the whole frame together.
  if (frame.sonar && !usePoints) {
    skippedSonar = frame;
    return;
  }
  skippedSonar = undefined;
  latest = { ...latest, ...telemetry };
  if (Object.hasOwn(frame, 'target')) latestTargetAt = performance.now();
  if (usePoints) pendingCloud = points;
}

function status(state) {
  const messages = {
    connecting: ['Connecting…', 'Opening the WebSocket.'],
    connected: ['Connected', 'Waiting for a frame from the bridge.'],
    error: ['Connection failed', 'Check the bridge URL, server, and allowed browser origin.'],
    complete: ['Replay complete', 'Showing the last recorded frame. Connect to replay again.'],
    disconnected: ['Local preview', 'Start the bridge, then connect.'],
  };
  connection.dataset.status = state;
  [connection.textContent, note.textContent] = messages[state];
  const busy = state === 'connected' || state === 'connecting';
  connect.textContent = busy ? 'Disconnect' : lidarSelected() ? 'Start session' : 'Connect';
  address.disabled = feedMode.disabled = busy;
  if (!busy) disconnect = undefined;
  if (lidarSelected()) {
    if (state === 'disconnected') {
      lidarPaused = false;
      set('connection-state', 'Disconnected');
      set('connection-note', lidarSample ? 'Showing the last view. Save it before starting a new session.'
        : 'Start the LiDAR relay, then start a session.');
    }
    updateLidarControls();
    if (!savedMap) showScanSource();
    return;
  }
  if (state === 'complete') {
    if (skippedSonar) applyFrame(skippedSonar, true);
    sonarReplayComplete = true;
  }
  if (!busy && state !== 'complete') {
    if (scanCameraBeforeSonar) {
      if (savedMap) scanSettings.camera = scanCameraBeforeSonar;
      else {
        view = scanCameraBeforeSonar.view;
        viewer?.follow(scanCameraBeforeSonar.state, view);
        updateViewLabel();
      }
    }
    scanCameraBeforeSonar = undefined;
    sonarReplayComplete = false;
    skippedSonar = undefined;
    frameSonar = false;
    live = false;
    pendingCloud = undefined;
    latest = {};
    lastTick = -1;
    latestTargetAt = undefined;
    livePoints = undefined;
    history.length = 0;
    if (!savedMap) showScanSource();
    updateModeAvailability();
  }
}

feedMode.addEventListener('change', () => {
  if (lidarSelected()) {
    scanCameraBeforeSonar ??= viewer?.camera();
    status('disconnected');
  } else {
    clearLidar();
    status('disconnected');
  }
  updateLidarControls();
  updateModeAvailability();
});

lidarPause.addEventListener('click', () => {
  lidarPaused = !lidarPaused;
  updateLidarControls();
});
lidarClear.addEventListener('click', () => {
  clearLidar(Boolean(disconnect));
  if (!savedMap) showScanSource();
  set('connection-note', disconnect ? 'Viewer cleared. Resume to receive the phone’s map again.' : 'Viewer cleared.');
});
el('lidar-file').addEventListener('change', async event => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  try {
    if (file.size > LIDAR_REPLAY_BYTES) throw new Error('Choose a LiDAR JSONL file up to 16 MB.');
    const scan = await readLidarReplay(await file.text());
    openSaved({ ...scan, name: file.name });
  } catch (error) {
    set('connection-note', `Replay could not open. ${error.message}`);
  }
});

el('connection-form').addEventListener('submit', event => {
  event.preventDefault();
  if (disconnect) {
    disconnect();
    return;
  }
  try {
    if (lidarSelected()) {
      clearLidar();
      if (!savedMap) showScanSource();
      disconnect = openFeed(address.value.trim(), {
        decode: decodeRelayLidar,
        onStatus: status,
        onInvalid: () => set('connection-note', 'Frame skipped. Expected a valid LiDAR relay envelope.'),
        onFrame: frame => {
          lidarSeenAt = performance.now();
          if (lidarPaused) return;
          const next = lidarMap.observe(frame);
          if (!next) return;
          if (lidarSample?.lidar.reference !== next.lidar.reference ||
              lidarSample?.lidar.sessionId !== next.lidar.sessionId ||
              lidarSample?.lidar.deviceId !== next.lidar.deviceId) {
            lidarFrameFit = true;
            history.length = 0;
          }
          lidarSample = { ...next, t: lidarSeenAt };
          sampleHistory(history, lidarSample);
          set('connection-note', next.lidar.sessionId ? `Session ${next.lidar.sessionId}`
            : next.lidar.reference === 'world' ? 'Showing the phone’s accumulated map. Pose unavailable.'
            : 'Showing only this view. Select Room map on the phone to retain geometry.');
          updateLidarControls();
          if (!savedMap) showScanSource();
        },
      });
      return;
    }
    let firstFrame = true;
    disconnect = openFeed(address.value.trim(), {
      decode: async payload => {
        const frame = await decodeSocketFrame(payload);
        if (frame.sonar?.modality === 'lidar') throw new Error('Choose the iPhone LiDAR feed.');
        return frame;
      },
      onStatus: status,
      onInvalid: () => { note.textContent = 'Message skipped. Unsupported or malformed frame.'; },
      onFrame: frame => {
        if (firstFrame) {
          firstFrame = false;
          scanCameraBeforeSonar ??= savedMap ? scanSettings.camera : viewer?.camera();
          live = true;
          sonarReplayComplete = false;
          skippedSonar = undefined;
          latest = {};
          latestTargetAt = undefined;
          pendingCloud = undefined;
          frameNumber = 0;
          history.length = 0;
          livePoints = emptyPoints;
          updateModeAvailability();
        }
        frameSonar ||= Boolean(frame.sonar && !livePoints?.length);
        applyFrame(frame);
        if (!savedMap) showScanSource();
        note.textContent = latest.sonar ? latest.sonar.detectionCount === null ? 'Detections unavailable.'
          : `${latest.sonar.detectionCount} model detections.` : 'Receiving preview frames.';
      },
    });
  } catch {
    status('error');
    note.textContent = 'Enter a valid ws:// or wss:// address.';
    address.focus();
  }
});

function place(node, position) {
  const projected = position && viewer.project(position);
  node.hidden = !projected;
  if (projected) {
    node.style.left = `${projected[0]}%`;
    node.style.top = `${projected[1]}%`;
  }
}

let started;
let lastMiniPoints, miniBounds;
const hud = el('hud-map');
const hudContext = hud.getContext('2d');
function drawOverview(points, target) {
  const ctx = hudContext, { width, height } = hud;
  if (points !== lastMiniPoints) {
    let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
    for (let i = 0; i < points.length; i += 3) {
      x0 = Math.min(x0, points[i]); x1 = Math.max(x1, points[i]);
      z0 = Math.min(z0, points[i + 2]); z1 = Math.max(z1, points[i + 2]);
    }
    const scale = Math.min((width - 24) / Math.max(1, x1 - x0), (height - 24) / Math.max(1, z1 - z0));
    miniBounds = points.length ? { x: (x0 + x1) / 2, z: (z0 + z1) / 2, scale } : { x: 0, z: 0, scale: 1 };
    lastMiniPoints = points;
  }
  const { x, z, scale } = miniBounds;
  const at = (u, v) => [(u - x) * scale + width / 2, (v - z) * scale + height / 2];
  ctx.fillStyle = '#0a141d';
  ctx.fillRect(0, 0, width, height);
  const meterStep = Math.max(1, Math.ceil(18 / scale));
  ctx.strokeStyle = '#253847';
  ctx.beginPath();
  for (let gx = Math.ceil((x - width / 2 / scale) / meterStep) * meterStep; gx < x + width / 2 / scale; gx += meterStep) {
    const [px] = at(gx, 0); ctx.moveTo(px, 0); ctx.lineTo(px, height);
  }
  for (let gz = Math.ceil((z - height / 2 / scale) / meterStep) * meterStep; gz < z + height / 2 / scale; gz += meterStep) {
    const [, py] = at(0, gz); ctx.moveTo(0, py); ctx.lineTo(width, py);
  }
  ctx.stroke();
  set('hud-scale', `${meterStep} m grid`);
  ctx.fillStyle = '#4ea5d0';
  const step = Math.max(3, 3 * Math.ceil(points.length / 15000));
  for (let i = 0; i < points.length; i += step) {
    const [px, py] = at(points[i], points[i + 2]); ctx.fillRect(px, py, 1.5, 1.5);
  }
  if (target) {
    const [px, py] = at(target.position[0], target.position[2]);
    ctx.fillStyle = '#edb467';
    ctx.beginPath(); ctx.arc(px, py, 4, 0, Math.PI * 2); ctx.fill();
  }
}

function configureSlice(points) {
  let low = Infinity, high = -Infinity;
  for (let i = 1; i < points.length; i += 3) {
    low = Math.min(low, points[i]);
    high = Math.max(high, points[i]);
  }
  sliceBounds = points.length ? [Math.floor(low * 10) / 10, Math.ceil(high * 10) / 10] : [0, 3.2];
  const height = el('slice-height');
  const value = Number(height.value);
  [height.min, height.max] = sliceBounds;
  height.value = Math.max(sliceBounds[0], Math.min(sliceBounds[1], value));
  updateSliceLabel();
}

el('save-scan').addEventListener('click', () => {
  if (!activeSample?.points.length || !renderOptions || savedMap) return;
  viewer.draw(renderOptions);
  const entry = { ...activeSample, t: sonarReplayComplete || activeSample.lidar ? activeSample.t : performance.now() };
  const samples = history.filter(sample => sample.t < entry.t);
  samples.push(entry);
  library.save({
    ...entry, id: crypto.randomUUID(), name: entry.lidar ? 'LiDAR scan' : live ? 'Room scan' : 'Living room snapshot',
    date: new Date().toISOString(), source: entry.lidar ? entry.lidar.acquisition === 'live' ? 'live' : 'mock'
      : live && latest.sonar?.acquisition !== 'simulated' ? 'live' : 'mock',
    space: live || entry.lidar ? null : MOCK_SPACE,
    history: samples, thumb: thumbnail(canvas),
  });
});

let archiveReady = false, trailKey, trail, activeSavedMap;
function render(time) {
  started ??= time;
  const elapsed = time - started;
  const tick = Math.floor(elapsed / 100);
  const scanningLidar = lidarSelected();
  if (!scanningLidar && !live && tick !== lastTick && tick % (Number(skip.value) + 1) === 0) {
    latest = mockFrame(motion.matches ? 0 : elapsed);
    lastTick = tick;
  }
  if (pendingCloud) {
    livePoints = pendingCloud;
    pendingCloud = undefined;
  }
  const latestTarget = live && !sonarReplayComplete &&
    (latestTargetAt === undefined || time - latestTargetAt > 1500) ? null : latest.target;
  activeSample = scanningLidar ? lidarSample ?? { points: emptyPoints } : { t: sonarReplayComplete ? latestTargetAt ?? time : time,
    target: latestTarget?.confidence >= 0.5 ? latestTarget : null,
    points: live ? livePoints ?? emptyPoints : demoPoints, frame: latest.frame, latencyMs: latest.latencyMs,
    sonar: latest.sonar, captureTime: latest.captureTime, snr: latest.snr };
  if (!scanningLidar && (!sonarReplayComplete || history.at(-1)?.frame !== activeSample.frame) &&
      (activeSample.points.length || history.length)) sampleHistory(history, activeSample);
  requestAnimationFrame(render);
  if (workspace !== 'scan') return;

  const frame = savedMap ? replay.frame(time) : { sample: activeSample, t: time, history };
  const sample = frame.sample ?? {};
  const displayPoints = savedMap || live || scanningLidar ? sample.points ?? emptyPoints : undefined;
  if (currentPoints !== displayPoints) {
    currentPoints = displayPoints;
    viewer.replaceCloud(displayPoints);
    configureSlice(displayPoints ?? demoPoints);
  }
  if ((!savedMap && (scanningLidar ? lidarFrameFit : frameSonar) ||
      (savedMap?.sonar || savedMap?.lidar) && activeSavedMap !== savedMap) && displayPoints?.length) {
    viewer.frameCloud(displayPoints);
    if (savedMap) activeSavedMap = savedMap;
    else if (scanningLidar) lidarFrameFit = false;
    else frameSonar = false;
  }
  const lidar = sample.lidar;
  const lidarView = Boolean(savedMap ? savedMap.lidar : scanningLidar);
  const target = sample.target ?? null;
  el('trail-enabled').disabled = lidarView || Boolean(sample.sonar);
  const inspectionTrail = el('trail-enabled').checked && !el('trail-enabled').disabled;
  const key = inspectionTrail ? frame.history.filter(entry => entry.t <= frame.t).at(-1) : null;
  if (key !== trailKey) {
    trailKey = key;
    trail = key ? frame.history.filter(entry => entry.t <= frame.t) : undefined;
  }
  const showRings = rings.checked && !(live || savedMap || lidarView);
  const pointLimit = Number(pointCap.value);
  const height = Number(el('slice-height').value);
  renderOptions = { mode: mode.value, pointSize: Number(pointSize.value), pointCap: pointLimit,
    showGrid: grid.checked, rings: showRings, target, meshTint: el('mesh-tint').value,
    heightRange: el('slice-enabled').checked ? [height - 0.22, height + 0.22] : undefined,
    trail, scanner: lidar?.scanner, scannerPath: lidar?.path, time: motion.matches ? 0 : tick * 100 };
  viewer.draw(renderOptions);
  el('sonar-legend').hidden = lidarView;
  el('lidar-legend').hidden = !lidarView;
  el('path-legend').hidden = !lidar?.path?.length;
  place(el('scanner-marker'), lidar?.scanner);
  const markerLabel = sample.sonar ? 'Sonar person estimate' : 'Estimated zone';
  if (marker.lastChild.textContent !== markerLabel) marker.lastChild.textContent = markerLabel;
  place(marker, target && [target.position[0], target.position[1] + 0.5, target.position[2]]);
  labels.forEach((label, i) => {
    const [x, , z] = anchors[i];
    place(label, showRings && [x, 0.5, z]);
  });
  el('camera-hud').hidden = view !== 'camera';
  if (view === 'camera') {
    set('heading', String(viewer.heading).padStart(3, '0') + '°');
    if (tick !== lastHud) {
      drawOverview(displayPoints ?? demoPoints, target);
      lastHud = tick;
    }
  }
  if (lastTelemetry !== tick) {
    lastTelemetry = tick;
    const vertexCount = mode.value === 'mesh' && viewer.hasMesh ? viewer.meshCount : viewer.count;
    set('vertices', numbers.format(Math.min(vertexCount, pointLimit)));
    set('frame', sample.frame ?? '—');
    set('signal-label', lidarView ? 'Depth confidence' : sample.sonar ? 'Mean SNR' : 'Latency');
    set('latency', lidarView ? lidar?.depthConfidence == null ? '—' : `${lidar.depthConfidence.toFixed(1)}/2`
      : sample.sonar ? sample.snr == null ? '—' : `${sample.snr.toFixed(1)}×`
      : sample.latencyMs === undefined ? '—' : `${Math.round(sample.latencyMs)} ms`);
    el('capture-clock').hidden = !(sample.sonar || lidar);
    set('capture-time', sample.captureTime === undefined ? '—' : `${sample.captureTime.toFixed(2)} s`);
    set('estimate-label', lidarView ? 'Tracking' : 'Confidence');
    const stale = !savedMap && lidarSeenAt !== undefined && time - lidarSeenAt > 2500;
    set('estimate', lidarView ? !savedMap && lidarPaused ? 'Display paused' : stale ? 'No recent frame'
      : lidar?.tracking?.replaceAll('_', ' ') ?? '—' : target ? `${Math.round(target.confidence * 100)}%` : 'Unknown');
    el('retained-count').hidden = !lidarView;
    set('retained', numbers.format(Math.floor((displayPoints?.length ?? 0) / 3)));
    if (savedMap) {
      let last = null;
      for (const entry of frame.history) {
        if (entry.t > frame.t) break;
        if (entry.target) last = entry;
      }
      const age = last ? ` · Last estimate ${Math.max(0, (frame.t - last.t) / 1000).toFixed(1)} s ago` : '';
      set('replay-estimate', lidarView ? (lidar?.reference === 'world' ? 'Room observations' : 'Phone-relative view') +
        (lidar?.scanner ? ' · Scanner pose available' : ' · Scanner pose unavailable')
        : (target ? `Estimate ${Math.round(target.confidence * 100)}%` : 'Location unknown') + age);
    }
    el('save-scan').disabled = !archiveReady || !activeSample.points.length;
  }
}

requestAnimationFrame(() => setTimeout(() => {
  try {
    const room = buildRoom();
    viewer = createViewer(canvas, room, undefined, resetScanCamera);
    viewer.preset(view, true);
    demoPoints = positions(room.cloud);
    configureSlice(demoPoints);
    currentPoints = unsetPoints;
    const seeds = sampleScans(room, viewer, canvas);
    openArchive().then(async store => {
      await store.initialize(seeds);
      await library.ready(store);
      archiveReady = true;
    }).catch(() => library.fail());
    loading.hidden = true;
    requestAnimationFrame(render);
  } catch (error) {
    loading.classList.add('error');
    loading.querySelector('span').textContent = error.message;
  }
}, 0));

if (location.hash === '#maps') show('library');
