import { buildRoom, anchors } from './room.js';
import { createViewer } from './viewer.js';
import { mockFrame } from './mock.js';
import { openFeed } from './feed.js';
import { decodeSocketFrame, sonarLabel, SONAR_URL } from './sonar.js';
import { createLidarSession, drawCoverage, lidarLabel, LIDAR_URL, LIDAR_REPLAY_BYTES, readLidarReplay } from './lidar.js';
import { createCues } from './audio-cues.js';
import { createMapperSession, mapperLabel, sonarText } from './mapper-adapter.js';
import { drawRoomPlan } from './room-plan.js';
import { classifyRoom, classNames } from './room-classifier.js';
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
const feedMode = el('feed-mode');
// The live sensor is the iPhone LiDAR. The sonar bridge is still at ws://127.0.0.1:8765/ws.
address.value = LIDAR_URL;
const cues = createCues();
const lidar = createLidarSession({ onEvent: name => cues.play(name) });
async function decodeLidar(payload) {
  const frame = await lidar.decode(payload);
  if (!frame) throw new Error('Expected LiDAR v1');
  return frame;
}
// Rishi's mapper (lidar/mapper) sends its map in the sonar envelope. Give it surface classes.
let mapper = createMapperSession();
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
let workspace = 'scan', savedMap, livePoints, liveColors, liveHits, currentPoints, demoPoints, latestTargetAt, scanSettings;
let activeSample, displayedSample, renderOptions, lastHud = -1, sliceBounds = [0, 3.2], frameSonar = false;
let scanCameraBeforeSonar;
let sonarReplayComplete = false, skippedSonar;
const emptyPoints = new Float32Array();
const unsetPoints = Symbol('reset geometry');
const history = [];
const library = createLibrary({ show, open: openSaved, scan: returnToScan });

function updateModeAvailability() {
  const external = Boolean(savedMap) || live;
  skip.disabled = Boolean(savedMap?.lidar || latest.lidar);
  mode.querySelector('[value="mesh"]').disabled = external;
  rings.disabled = external;
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
  el('room-analysis').hidden = true;
  el('replay-analyse').hidden = !map.lidar;
  mode.querySelector('[value="color"]').textContent = map.lidar ? 'Surface classes' : 'Natural color';
  if (map.lidar) mode.value = 'color';
  currentPoints = unsetPoints;
  activeSavedMap = undefined;
  replay.open(map);
  el('replay').hidden = false;
  el('scan-capture').hidden = true;
  el('connection-form').hidden = true;
  el('connection-note').hidden = true;
  el('feed-mode-row').hidden = el('lidar-file-row').hidden = el('lidar-panel').hidden = true;
  updateModeAvailability();
  el('mapper-tools').hidden = el('sonar-readout').hidden = true;
  writeSource(map.mapper ? mapperLabel({ ...map.mapper, delivery: 'recorded' })
    : map.lidar ? lidarLabel({ ...map.lidar, mode: 'replay' }) : map.sonar ? `Saved · ${sonarLabel(map.sonar)}` : map.source === 'mock' ? 'Saved · Mock' : 'Saved · Live');
  source.removeAttribute('data-live');
  set('study', map.name);
  show('scan');
  el('back-library').focus();
}

function returnToScan() {
  if (savedMap) {
    replay.pause();
    el('room-analysis').hidden = true;
    savedMap = undefined;
    currentPoints = unsetPoints;
    el('replay').hidden = true;
    el('scan-capture').hidden = false;
    el('connection-form').hidden = false;
    el('connection-note').hidden = false;
    el('feed-mode-row').hidden = false;
    el('lidar-file-row').hidden = feedMode.value !== 'lidar';
    mode.value = scanSettings.mode;
    const { state, view: previousView } = scanSettings.camera;
    view = previousView;
    viewer.follow(state, view);
    updateViewLabel();
    updateModeAvailability();
    configureSlice(live ? livePoints ?? emptyPoints : demoPoints);
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
  if ((savedMap?.sonar || savedMap?.lidar || !savedMap && (latest.sonar || latest.lidar)) && currentPoints instanceof Float32Array) {
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
  const sonar = latest.sonar, scan = latest.lidar;
  const mapped = live && !scan ? latest.mapper : null;
  source.toggleAttribute('data-live', live && (scan ? Boolean(disconnect && scan.publisher && scan.simulated === false && scan.mode === 'live')
    : Boolean(disconnect && (mapped ? !mapped.stale && mapped.delivery === 'live' && mapped.acquisition === 'live'
      : sonar?.delivery === 'live' && sonar?.acquisition === 'live'))));
  writeSource(!live ? 'Mock data' : scan ? (disconnect || scan.mode === 'replay' ? '' : 'Last scan · ') + lidarLabel(scan)
    : mapped ? mapperLabel(mapped) : sonar ? sonarLabel(sonar) : 'Socket data');
  set('study', !live ? 'Living room / sample scan' : scan ? 'LiDAR · Spatial memory'
    : mapped ? 'LiDAR · Mapped room' : sonar ? 'Sonar · Sensor-relative scan' : 'Incoming room scan');
  el('mapper-tools').hidden = !mapped;
  el('sonar-readout').hidden = !mapped || !mapped.stale && !mapped.sonar;
  el('lidar-panel').hidden = !(live && scan);
  // In LiDAR mode the "color" render mode shows the classifier's surface classes.
  mode.querySelector('[value="color"]').textContent = live && (scan || mapped) ? 'Surface classes' : 'Natural color';
  if (live && (scan || mapped) && !classModeChosen) {
    classModeChosen = true;
    mode.value = 'color';
    setMode();
  }
  if (!(live && (scan || mapped))) {
    classModeChosen = false;
    el('room-analysis').hidden = true;
  }
}

const trackingText = { normal: 'Tracking', limited: 'Tracking limited', not_available: 'No tracking' };
let coverageRevision = -1, classModeChosen = false, planPoints;
function showRoomAnalysis(force = false) {
  const sample = displayedSample;
  if (el('room-analysis').hidden || !(sample?.lidar || sample?.mapper) || !force && planPoints === sample.points) return;
  planPoints = sample.points;
  const analysis = sample.mapper && !sample.lidar ? mapper.analysis
    : savedMap ? classifyRoom(sample.points, { hits: sample.hits }) : lidar.analyse();
  // The mapper does not send the scanner path on this channel, so none is drawn.
  const { path, simulated } = sample.lidar ?? { path: [], simulated: sample.mapper?.acquisition === 'simulated' };
  const sonarSurface = sample.mapper && !sample.lidar ? mapper.sonarSurface : [];
  const lastGap = path.lastIndexOf(null);
  // The plan renderer draws one polyline; avoid joining across missing poses.
  drawRoomPlan(el('room-plan'), analysis, { path: path.slice(lastGap + 1), simulated, sonarSurface,
    attribution: sample.mapper ? mapperLabel(sample.mapper) : '' });
  const total = analysis.labels.length || 1;
  set('room-analysis-note', classNames.slice(1).map((name, i) =>
    `${name} ${Math.round(analysis.counts[i + 1] / total * 100)}%`).join(' · ') +
    ` of ${numbers.format(analysis.labels.length)} points` + (lastGap >= 0 ? ' · Path since last gap' : ''));
}
for (const id of ['lidar-analyse', 'replay-analyse', 'mapper-analyse']) {
  el(id).addEventListener('click', () => {
    el('room-analysis').hidden = !el('room-analysis').hidden;
    showRoomAnalysis(true);
  });
}
el('room-analysis-close').addEventListener('click', () => { el('room-analysis').hidden = true; });
el('room-plan-download').addEventListener('click', event => {
  event.currentTarget.href = el('room-plan').toDataURL('image/png');
});
function showLidarStatus(scan) {
  const { stats } = scan;
  note.textContent = scan.mode === 'live' && !scan.publisher ? 'Waiting for the phone to connect to the bridge.'
    : `${trackingText[scan.tracking] ?? 'Waiting for a frame'}${scan.paused ? ' · display paused' : ''}` +
      `${scan.recording ? ' · recording' : ''}. ${stats.framesSkipped} frames skipped without tracking.`;
  set('lidar-observed', `${stats.observedArea.toFixed(1)} m²`);
  set('lidar-path', `${stats.pathMeters.toFixed(1)} m`);
  set('lidar-voxels', numbers.format(stats.voxels) + (stats.dropped ? ' (full)' : ''));
  if (coverageRevision !== lidar.memory.revision) {
    coverageRevision = lidar.memory.revision;
    drawCoverage(el('coverage-map'), lidar.memory, scan.path);
  }
}
el('lidar-clear').addEventListener('click', () => {
  lidar.clear();
  if (!live || !latest.lidar) return;
  history.length = 0;
  frameSonar = true;
  if (disconnect) lidar.setPaused(true);
  showLidarPause();
  applyFrame(lidar.current(), true);
  showLidarStatus(latest.lidar);
});
function showLidarPause() {
  el('lidar-pause').textContent = lidar.paused ? 'Resume display' : 'Pause display';
  el('lidar-pause').setAttribute('aria-pressed', String(lidar.paused));
}
el('lidar-pause').addEventListener('click', () => {
  lidar.setPaused(!lidar.paused);
  showLidarPause();
  if (!live || !latest.lidar) return;
  applyFrame(lidar.current(), true);
  showLidarStatus(latest.lidar);
});
el('lidar-file').addEventListener('change', async event => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  try {
    if (file.size > LIDAR_REPLAY_BYTES) throw new Error('Choose a LiDAR JSONL recording up to 16 MB.');
    const scan = await readLidarReplay(await file.text());
    openSaved({ ...scan, name: file.name });
  } catch (error) {
    set('connection-note', `Replay could not open. ${error.message}`);
  }
});
// The library writes this text once a snapshot is actually stored.
new MutationObserver(() => {
  if (el('capture-status').textContent === 'Snapshot saved') cues.play('scan_saved');
}).observe(el('capture-status'), { childList: true });
el('lidar-audio').addEventListener('change', event => cues.setEnabled(event.currentTarget.checked));

function applyFrame(frame, force = false) {
  const { points, colors, hits, ...telemetry } = frame;
  const usePoints = points && (force || frame.lidar || !points.length || frameNumber++ % (Number(skip.value) + 1) === 0);
  // A sonar detection is relative to its own frame. Skip the whole frame together.
  if (frame.sonar && !usePoints) {
    skippedSonar = frame;
    return;
  }
  skippedSonar = undefined;
  latest = { ...latest, ...telemetry };
  if (Object.hasOwn(frame, 'target')) latestTargetAt = performance.now();
  if (usePoints) pendingCloud = { points, colors, hits };
}

function status(state) {
  const messages = {
    connecting: ['Connecting…', 'Opening the WebSocket.'],
    connected: ['Connected', 'Waiting for a frame from the bridge.'],
    error: ['Connection failed', 'Check the bridge URL, server, and allowed browser origin.'],
    complete: ['Replay complete', 'Showing the last recorded frame. Connect to replay again.'],
    disconnected: ['Local preview', 'Start the bridge, then connect.'],
    preview: ['Local preview', 'Explicit mock preview selected. No sensor observations.'],
  };
  connection.dataset.status = state;
  [connection.textContent, note.textContent] = messages[state];
  const busy = state === 'connected' || state === 'connecting';
  connect.textContent = busy ? 'Disconnect' : 'Connect';
  address.disabled = feedMode.disabled = busy;
  if (!busy) disconnect = undefined;
  if (state === 'complete') {
    if (skippedSonar) applyFrame(skippedSonar, true);
    sonarReplayComplete = true;
    cues.play('replay_complete');
  }
  if (!busy && state !== 'preview' && latest.mapper) {
    // A disconnected feed is historical evidence, never a reason to invent a new room.
    sonarReplayComplete = true;
    latest.mapper = { ...latest.mapper, stale: true, sonar: null };
    planPoints = undefined;
    set('connection-state', state === 'complete' ? 'Replay complete' : state === 'error' ? 'Connection lost' : 'Disconnected');
    set('connection-note', 'Showing last map (historical). Feed is not current. Connect again or select Mock preview.');
    const readout = el('sonar-readout');
    readout.textContent = 'Sonar unavailable: feed disconnected; previous markers are historical.';
    readout.removeAttribute('data-blind');
    readout.hidden = Boolean(savedMap);
    if (!savedMap) showScanSource();
    return;
  }
  if (!busy && state !== 'complete' && state !== 'preview' && feedMode.value === 'lidar' && latest.lidar && livePoints?.length) {
    // Leave the operator's observations in view after a disconnect.
    sonarReplayComplete = true;
    if (latest.lidar.mode === 'live') latest.lidar = { ...latest.lidar, publisher: false, scanner: null };
    set('connection-state', state === 'error' ? 'Connection lost' : 'Disconnected');
    set('connection-note', 'Showing the last scan. Save it before connecting again.');
    if (!savedMap) showScanSource();
    return;
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
    livePoints = liveColors = liveHits = undefined;
    history.length = 0;
    if (!savedMap) showScanSource();
    updateModeAvailability();
  }
}

feedMode.addEventListener('change', () => {
  address.value = feedMode.value === 'lidar' ? LIDAR_URL : SONAR_URL;
  el('lidar-file-row').hidden = feedMode.value !== 'lidar';
  if (feedMode.value === 'mock') status('preview');
  else if (feedMode.value === 'sonar') status('disconnected');
  connect.disabled = address.disabled = feedMode.value === 'mock';
});

el('connection-form').addEventListener('submit', event => {
  event.preventDefault();
  if (feedMode.value === 'mock') return;
  if (disconnect) {
    disconnect();
    return;
  }
  try {
    let firstFrame = true;
    lidar.reset();
    // Keep the historical room analysis until a valid frame from the new connection arrives.
    const incomingMapper = createMapperSession();
    showLidarPause();
    disconnect = openFeed(address.value.trim(), {
      decode: feedMode.value === 'lidar' ? decodeLidar
        : async payload => await incomingMapper.decode(payload) ?? decodeSocketFrame(payload),
      onStatus: status,
      onInvalid: () => { note.textContent = 'Message skipped. Unsupported or malformed frame.'; },
      onFrame: frame => {
        if (firstFrame) {
          mapper = incomingMapper;
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
          liveColors = liveHits = undefined;
          updateModeAvailability();
        }
        const scan = frame.lidar;
        if (scan && (!latest.lidar || scan.sessionId !== latest.lidar.sessionId ||
            scan.deviceId !== latest.lidar.deviceId || scan.simulated !== latest.lidar.simulated)) {
          history.length = 0;
          frameSonar = true;
        }
        frameSonar ||= Boolean((frame.sonar || frame.lidar) && !livePoints?.length);
        applyFrame(frame);
        updateModeAvailability();
        if (!savedMap) showScanSource();
        if (latest.lidar) showLidarStatus(latest.lidar);
        else if (latest.mapper) {
          const m = latest.mapper;
          note.textContent = `${numbers.format(m.mapPoints)} map points · ${m.objects} object${m.objects === 1 ? '' : 's'} · ` +
            `floor seen ${m.floorArea.toFixed(1)} m²` + (m.roomHeight === null ? '' : ` · ceiling ${m.roomHeight.toFixed(2)} m`);
          const readout = el('sonar-readout');
          readout.hidden = Boolean(savedMap) || !m.sonar;
          if (m.sonar) {
            readout.textContent = sonarText(m.sonar) + (m.sonar.surfacePoints ? ` · ${m.sonar.surfacePoints} marked` : '');
            readout.toggleAttribute('data-blind', m.sonar.blind);
            if (m.sonar.blind) cues.play('lidar_blind');
          }
          showRoomAnalysis();
        } else note.textContent = latest.sonar ? latest.sonar.detectionCount === null ? 'Detections unavailable.'
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
  const entry = { ...activeSample, t: sonarReplayComplete ? activeSample.t : performance.now() };
  const samples = history.filter(sample => sample.t < entry.t);
  samples.push(entry);
  library.save({
    ...entry, id: crypto.randomUUID(), name: live ? 'Room scan' : 'Living room snapshot',
    date: new Date().toISOString(),
    source: latest.mapper ? (latest.mapper.acquisition === 'live' ? 'live'
      : latest.mapper.acquisition === 'simulated' ? 'mock' : 'recorded')
      : live && latest.sonar?.acquisition !== 'simulated' && !latest.lidar?.simulated ? 'live' : 'mock',
    space: live ? null : MOCK_SPACE,
    history: samples, thumb: thumbnail(canvas),
  });
});

let archiveReady = false, trailKey, trail, activeSavedMap, activeSavedOrigin;
function render(time) {
  started ??= time;
  const elapsed = time - started;
  const tick = Math.floor(elapsed / 100);
  if (!live && tick !== lastTick && tick % (Number(skip.value) + 1) === 0) {
    latest = mockFrame(motion.matches ? 0 : elapsed);
    lastTick = tick;
  }
  if (pendingCloud) {
    ({ points: livePoints, colors: liveColors, hits: liveHits } = pendingCloud);
    pendingCloud = undefined;
  }
  const latestTarget = live && !sonarReplayComplete &&
    (latestTargetAt === undefined || time - latestTargetAt > 1500) ? null : latest.target;
  activeSample = { t: sonarReplayComplete ? latestTargetAt ?? time : time,
    target: latestTarget?.confidence >= 0.5 ? latestTarget : null,
    points: live ? livePoints ?? emptyPoints : demoPoints, colors: liveColors, hits: liveHits,
    frame: latest.frame, latencyMs: latest.latencyMs,
    sonar: latest.sonar, lidar: latest.lidar, mapper: live ? latest.mapper : undefined,
    captureTime: latest.captureTime, snr: latest.snr };
  if (!activeSample.lidar?.paused && (!activeSample.lidar || history.at(-1)?.frame !== activeSample.frame) &&
      (!sonarReplayComplete || history.at(-1)?.frame !== activeSample.frame) &&
      (activeSample.points.length || history.length)) sampleHistory(history, activeSample);
  requestAnimationFrame(render);
  if (workspace !== 'scan') return;

  const frame = savedMap ? replay.frame(time) : { sample: activeSample, t: time, history };
  const sample = frame.sample ?? {};
  displayedSample = sample;
  const displayPoints = savedMap || live ? sample.points ?? emptyPoints : undefined;
  if (currentPoints !== displayPoints) {
    currentPoints = displayPoints;
    viewer.replaceCloud(displayPoints, sample.colors);
    configureSlice(displayPoints ?? demoPoints);
  }
  const scan = sample.lidar;
  const origin = scan ? JSON.stringify([scan.deviceId, scan.sessionId, scan.simulated]) : null;
  if ((!savedMap && frameSonar || (savedMap?.sonar || savedMap?.lidar) &&
      (activeSavedMap !== savedMap || activeSavedOrigin !== origin)) && displayPoints?.length) {
    viewer.frameCloud(displayPoints);
    if (savedMap) {
      activeSavedMap = savedMap;
      activeSavedOrigin = origin;
    }
    else frameSonar = false;
  }
  const target = sample.target ?? null;
  el('trail-enabled').disabled = Boolean(sample.sonar || sample.lidar);
  const inspectionTrail = el('trail-enabled').checked && !el('trail-enabled').disabled;
  const key = inspectionTrail ? frame.history.filter(entry => entry.t <= frame.t).at(-1) : null;
  if (key !== trailKey) {
    trailKey = key;
    trail = key ? frame.history.filter(entry => entry.t <= frame.t) : undefined;
  }
  const showRings = rings.checked && !(live || savedMap);
  const pointLimit = Number(pointCap.value);
  const height = Number(el('slice-height').value);
  renderOptions = { mode: mode.value, pointSize: Number(pointSize.value), pointCap: pointLimit,
    showGrid: grid.checked, rings: showRings, target, meshTint: el('mesh-tint').value,
    heightRange: el('slice-enabled').checked ? [height - 0.22, height + 0.22] : undefined,
    trail, scanner: scan?.scanner, scannerPath: scan?.path, time: motion.matches ? 0 : tick * 100 };
  viewer.draw(renderOptions);
  showRoomAnalysis();
  el('lidar-legend').hidden = !scan && !savedMap?.lidar;
  el('sonar-legend').hidden = !el('lidar-legend').hidden;
  place(el('scanner-marker'), scan?.scanner);
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
    set('signal-label', sample.lidar ? 'Tracking' : sample.mapper ? 'Mean hits per cell' : sample.sonar ? 'Mean SNR' : 'Latency');
    set('latency', sample.lidar ? trackingText[sample.lidar.tracking] ?? '—'
      : sample.sonar ? sample.snr == null ? '—' : `${sample.snr.toFixed(1)}×`
      : sample.latencyMs === undefined ? '—' : `${Math.round(sample.latencyMs)} ms`);
    el('capture-clock').hidden = !(sample.sonar || sample.lidar);
    set('capture-time', sample.captureTime === undefined ? '—' : `${sample.captureTime.toFixed(2)} s`);
    set('estimate-label', scan ? 'Observed points' : 'Confidence');
    set('estimate', scan ? numbers.format(scan.stats.voxels) : target ? `${Math.round(target.confidence * 100)}%` : 'Unknown');
    if (savedMap) {
      let last = null;
      for (const entry of frame.history) {
        if (entry.t > frame.t) break;
        if (entry.target) last = entry;
      }
      const age = last ? ` · Last estimate ${Math.max(0, (frame.t - last.t) / 1000).toFixed(1)} s ago` : '';
      if (scan) {
        writeSource(lidarLabel({ ...scan, mode: 'replay' }));
        set('replay-estimate', `${numbers.format(scan.stats.voxels)} observations · ${scan.stats.pathMeters.toFixed(1)} m of scanner path`);
      } else set('replay-estimate', (target ? `Estimate ${Math.round(target.confidence * 100)}%` : 'Location unknown') + age);
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
