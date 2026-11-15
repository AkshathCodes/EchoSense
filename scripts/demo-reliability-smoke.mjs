/** Software-only mapper/browser preflight. No serial access; only owned processes are stopped.
 * ECHO_PYTHON and ECHO_PLAYWRIGHT_MODULE may point to existing isolated dependencies.
 * Every run writes a new timestamped artifact directory; no previous results are replaced.
 */
import { spawn, execFileSync } from 'node:child_process';
import { once } from 'node:events';
import { createServer } from 'node:net';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join, resolve, delimiter } from 'node:path';
import { fixedMapperMessage } from './fixtures/mapper-regression.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const baseline = JSON.parse(await readFile(new URL('./fixtures/main-86a767c.json', import.meta.url)));
const artifacts = join(root, '.venv', 'reliability', new Date().toISOString().replaceAll(':', '-'));
await mkdir(artifacts, { recursive: true });
const python = process.env.ECHO_PYTHON || join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const playwright = process.env.ECHO_PLAYWRIGHT_MODULE || join(root, '.venv/browser/node_modules/playwright/index.mjs');
const env = { ...process.env, PYTHONPATH: [join(root, 'lidar/mapper/src'), process.env.PYTHONPATH].filter(Boolean).join(delimiter),
  OPENBLAS_NUM_THREADS: '1', OMP_NUM_THREADS: '1' };
const children = [], assertions = {};
const report = { commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
  dirty: execFileSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' }).trim(), assertions, results: {} };
const results = report.results;
let browser, browserServer, page, mapper;
const delay = ms => new Promise(r => setTimeout(r, ms));
const check = (name, passed) => { assertions[name] = Boolean(passed); };
async function free(port) {
  await new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', error => reject(new Error(`Port ${port} unavailable: ${error.message}`)));
    server.listen(port, '127.0.0.1', () => server.close(resolve));
  });
}
function launch(command, args, environment = env) {
  const p = spawn(command, args, { cwd: root, env: environment, stdio: ['ignore', 'pipe', 'pipe'] });
  children.push(p); p.logs = ''; p.launchError = null;
  p.on('error', error => { p.launchError = error; });
  p.stdout.on('data', b => { p.logs += b; }); p.stderr.on('data', b => { p.logs += b; });
  return p;
}
async function waitUntil(check, description, timeout = 180000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) { if (await check()) return; await delay(100); }
  throw new Error(`Timed out: ${description}`);
}
async function stop(p) {
  if (!p?.pid || p.exitCode !== null || p.signalCode !== null) return;
  const exited = once(p, 'exit');
  if (process.platform === 'win32') {
    const killer = spawn('taskkill', ['/pid', String(p.pid), '/t', '/f'], { stdio: 'ignore' });
    await once(killer, 'exit');
  } else p.kill();
  await Promise.race([exited, delay(3000)]);
  p.stdin?.destroy(); p.stdout?.destroy(); p.stderr?.destroy(); p.unref();
}
async function startMapper(args) {
  await free(8765); await free(8780);
  if (args[0] === 'serve') await free(8770);
  mapper = launch(python, ['-u', '-B', '-m', 'lidar_mapper', ...args]);
  await waitUntil(() => {
    if (mapper.launchError) throw mapper.launchError;
    if (mapper.exitCode !== null) throw new Error(`Mapper exited: ${mapper.logs}`);
    return mapper.logs.includes('[viewer] ws://') || mapper.logs.includes('EchoSense viewer ->');
  }, 'mapper ready', 600000);
}
async function connect() {
  await page.locator('#connection-form').evaluate(form => form.requestSubmit());
}
async function planText(target = page, button = 'mapper-analyse') {
  return target.evaluate(button => {
    const texts = [], original = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function(text, ...args) {
      // Trained schematics draw the floor plan to an offscreen canvas first.
      texts.push(String(text));
      return original.call(this, text, ...args);
    };
    try {
      document.getElementById('room-analysis').hidden = true;
      document.getElementById(button).click();
    } finally { CanvasRenderingContext2D.prototype.fillText = original; }
    return texts;
  }, button);
}
async function disconnectCheck(prefix) {
  await stop(mapper);
  await waitUntil(async () => /lost|disconnected/i.test(await page.locator('#connection-state').innerText()), 'disconnect shown', 15000);
  await delay(250); // Let the normal render loop publish the historical metadata.
  const state = await page.evaluate(() => ({ source: document.getElementById('source').textContent,
    status: document.getElementById('connection-state').textContent, vertices: document.getElementById('vertices').textContent,
    live: document.getElementById('source').hasAttribute('data-live'), sonar: document.getElementById('sonar-readout').textContent }));
  results[prefix] = state;
  check(`${prefix}: historical map retained`, /historical/.test(state.source) && !/Mock/.test(state.source) && parseInt(state.vertices.replaceAll(',', '')) > 0);
  check(`${prefix}: no active indicator`, !state.live);
  check(`${prefix}: stale sonar`, /unavailable.*disconnected/.test(state.sonar) && !/\d\.\d+ m/.test(state.sonar));
  const texts = await planText();
  check(`${prefix}: historical PNG attribution`, texts.some(t => /historical/.test(t)));
}
async function savedSnapshot(prefix, expected) {
  const previousMockCount = await page.locator('#mock-maps').textContent();
  await page.locator('#room-analysis-close').evaluate(button => button.click());
  await page.locator('#save-scan').click();
  await page.locator('#map-name').fill(`Synthetic reliability ${prefix}`);
  await page.locator('#confirm-map').click();
  const card = page.locator('.map-card').filter({ hasText: `Synthetic reliability ${prefix}` });
  await card.waitFor();
  check(`${prefix}: saved badge attribution`, expected.test(await card.locator('.map-source').innerText()));
  if (prefix === 'unknown') check('unknown acquisition not counted as mock', await page.locator('#mock-maps').textContent() === previousMockCount);
  await card.locator('.map-preview').click();
  await delay(500); // Background live messages must not re-enable archived telemetry.
  check(`${prefix}: archived replay attribution`, expected.test(await page.locator('#source').innerText())
    && /replay/.test(await page.locator('#source').innerText()) && await page.locator('#source').getAttribute('data-live') === null);
  check(`${prefix}: archive hides active telemetry`, await page.locator('#sonar-readout').isHidden()
    && await page.locator('#mapper-tools').isHidden());
  const texts = await planText(page, 'replay-analyse');
  check(`${prefix}: archived trained analysis attribution`, texts.some(t => /replay/.test(t))
    && texts.some(t => /LiDAR surface forest v1/.test(t)));
  const stored = await page.evaluate(async name => {
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open('echosense-archive', 1);
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    try {
      return await new Promise((resolve, reject) => {
        const request = db.transaction('scans').objectStore('scans').getAll();
        request.onsuccess = () => {
          const map = request.result.find(map => map.name === name);
          resolve({ model: map.mapper.analysis.model, labels: map.mapper.analysis.labels.length,
            points: map.mapper.mapPoints, markers: map.mapper.sonarSurface.length });
        };
        request.onerror = () => reject(request.error);
      });
    } finally { db.close(); }
  }, `Synthetic reliability ${prefix}`);
  check(`${prefix}: archived report and own markers persisted`, stored.model === baseline.model
    && stored.labels === stored.points && (prefix !== 'simulation' || stored.markers > 0));
  await page.locator('#scan-nav').click();
  await delay(200);
  check(`${prefix}: return to current map`, await page.locator('#replay').isHidden()
    && await page.locator('#scan-capture').isVisible() && await page.locator('#mapper-tools').isVisible());
}
try {
  for (const port of [4173, 8765, 8770, 8780]) await free(port);
  check('ports initially free', true);
  const { chromium } = await import(pathToFileURL(resolve(playwright)));
  const web = launch(process.execPath, ['serve.js'], { ...env, PORT: '4173', HOST: '127.0.0.1' });
  await waitUntil(() => { if (web.launchError) throw web.launchError; return web.logs.includes('EchoSense:'); }, 'static server', 15000);
  browserServer = await chromium.launchServer({ headless: true,
    channel: process.env.ECHO_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined), args: ['--use-angle=swiftshader'] });
  children.push(browserServer.process());
  browser = await chromium.connect(browserServer.wsEndpoint());
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }); page.setDefaultTimeout(30000);
  // Fault injection is confined to this test page; production worker code is unchanged.
  await page.addInitScript(() => {
    const NativeWorker = window.Worker;
    window.__heldMapperResults = [];
    window.Worker = class extends NativeWorker {
      constructor(url, options) { super(url, options); this.mapperWorker = String(url).includes('lidar-analysis-worker.js'); }
      set onmessage(handler) {
        super.onmessage = event => {
          if (this.mapperWorker && window.__holdMapperResults) window.__heldMapperResults.push(() => handler(event));
          else handler(event);
        };
      }
    };
  });
  const errors = [], states = new Set(), workers = []; let frames = 0, lastFrame, markedFrame;
  page.on('worker', worker => workers.push(worker.url()));
  page.on('pageerror', e => errors.push(e.message));
  page.on('websocket', socket => socket.on('framereceived', event => {
    try {
      const raw = JSON.parse(event.payload);
      if (raw.frame?.meta?.kind === 'lidar_map') {
        frames++; lastFrame = raw;
        if (raw.frame.meta.sonar) states.add(raw.frame.meta.sonar.state);
        if (raw.frame.meta.sonar?.surface_points > 0) markedFrame = raw;
      }
    } catch { /* Dense binary packets are inspected separately below. */ }
  }));
  await page.goto('http://127.0.0.1:4173/');
  await page.waitForFunction(() => document.getElementById('loading').hidden);
  check('initial mock preview labelled', /Mock data/.test(await page.locator('#source').innerText()));
  results.fixedWorker = await page.evaluate(async payload => {
    const { createMapperSession } = await import('/src/mapper-adapter.js');
    const { createMapperClassifier } = await import('/src/mapper-classifier.js');
    const frame = await createMapperSession({ classify: createMapperClassifier() }).decode(payload);
    const sha = async data => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', data)),
      n => n.toString(16).padStart(2, '0')).join('');
    const bytes = data => new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    return { model: frame.mapper.analysis.model, labels: await sha(bytes(frame.mapper.analysis.labels)),
      colors: await sha(bytes(frame.colors)), geometry: await sha(bytes(frame.points)),
      analysis: await sha(new TextEncoder().encode(JSON.stringify(frame.mapper.analysis))) };
  }, fixedMapperMessage());
  check('actual browser worker executes trained forest', workers.some(url => url.endsWith('lidar-analysis-worker.js'))
    && results.fixedWorker.model === baseline.model);
  check('browser predictions/colors/full analysis equal original main baseline',
    ['labels', 'colors', 'geometry', 'analysis'].every(key => results.fixedWorker[key] === baseline[key]));
  await page.locator('#feed-mode').selectOption('sonar');
  console.log('Testing actual simulated mapper /ws, sonar, Room analysis and PNG.');
  await startMapper(['sim', '--frames', '80', '--serve', '--sonar-sim', '--viewer-points', '50000']);
  await connect();
  await waitUntil(async () => frames > 3 && /map points/.test(await page.locator('#connection-note').innerText()), 'actual mapper frames mounted');
  check('actual mapper feed mounted', (await page.locator('#address').inputValue()) === 'ws://127.0.0.1:8765/ws');
  await waitUntil(() => states.has('agree') && markedFrame, 'agreement and sonar markers');
  results.frames = frames; results.sonarStates = [...states];
  results.wireProvenance = { source: lastFrame.source, acquisition_source: lastFrame.acquisition_source };
  check('simulation wire provenance', lastFrame.source === 'simulated' && lastFrame.acquisition_source === 'simulated');
  check('simulated map label', /Simulated/.test(await page.locator('#source').innerText()));
  check('simulation has no live indicator', await page.locator('#source').getAttribute('data-live') === null);
  check('simulated sonar label', /Simulated sonar/.test(await page.locator('#sonar-readout').innerText()));
  check('sonar markers transported', markedFrame.frame.points.some(row => row[3] >= 200));
  results.planText = await planText();
  results.roomAnalysis = await page.locator('#room-analysis-note').innerText();
  check('Room analysis', /Floor/.test(results.roomAnalysis) && /Wall/.test(results.roomAnalysis));
  check('main viewer uses trained worker schematic', /LiDAR surface forest v1/.test(results.roomAnalysis)
    && results.planText.some(t => /UNCLASSIFIED.*observed, uncertain/.test(t)) && workers.length >= 2);
  check('PNG simulation attribution', results.planText.includes('SIMULATED DATA'));
  check('unknown regions remain unknown', results.planText.some(t => /not the same as empty or safe/.test(t)));
  // Real download, not merely a data URL attribute.
  const downloaded = page.waitForEvent('download');
  await page.locator('#room-plan-download').evaluate(link => link.click());
  const download = await downloaded; await download.saveAs(join(artifacts, 'simulated-room.png'));
  check('PNG export', (await download.failure()) === null && download.suggestedFilename().endsWith('.png'));
  const dense = new WebSocket('ws://127.0.0.1:8780/map'); dense.binaryType = 'arraybuffer';
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { dense.close(); reject(new Error('dense map timeout')); }, 10000);
    dense.onmessage = e => { results.denseBytes = e.data.byteLength; clearTimeout(timer); dense.close(); resolve(); };
    dense.onerror = e => { clearTimeout(timer); reject(e); };
  });
  check('dense map transport', (await fetch('http://127.0.0.1:8780/')).status === 200 && results.denseBytes > 0);
  await savedSnapshot('simulation', /Simulated LiDAR map/);
  console.log('Testing actual browser worker failure and geometric fallback.');
  const fallbackPage = await browser.newPage();
  await fallbackPage.route('**/src/lidar-analysis-worker.js', route => route.abort());
  await fallbackPage.goto('http://127.0.0.1:4173/');
  await fallbackPage.waitForFunction(() => document.getElementById('loading').hidden);
  await fallbackPage.locator('#feed-mode').selectOption('sonar');
  await fallbackPage.locator('#connection-form').evaluate(form => form.requestSubmit());
  await waitUntil(async () => /Geometric fallback/.test(await fallbackPage.locator('#connection-note').innerText()), 'worker failure fallback', 30000);
  const fallbackText = await planText(fallbackPage);
  check('actual browser worker failure preserves geometric fallback', /Geometric fallback/.test(await fallbackPage.locator('#room-analysis-note').innerText())
    && fallbackText.includes('SIMULATED DATA') && (await fallbackPage.locator('#room-plan').getAttribute('height')) === '660');
  await fallbackPage.screenshot({ path: join(artifacts, 'geometric-fallback.png') });
  await fallbackPage.close();
  await page.locator('#room-analysis-close').evaluate(button => button.click());
  await page.screenshot({ path: join(artifacts, 'connected.png') });
  await disconnectCheck('transport loss');
  await page.screenshot({ path: join(artifacts, 'disconnected.png') });

  console.log('Testing failed reconnect, reconnect to simulation, explicit mock selection.');
  await connect(); // Server is absent: history must survive both connecting and error.
  check('connecting preserves historical map', /historical/.test(await page.locator('#source').innerText()));
  await waitUntil(async () => /lost|failed/i.test(await page.locator('#connection-state').innerText()), 'failed reconnect', 15000);
  check('failed reconnect preserves historical map', /historical/.test(await page.locator('#source').innerText()));
  const previousFrames = frames;
  await startMapper(['sim', '--frames', '8', '--serve', '--sonar-sim']);
  await connect();
  await waitUntil(async () => frames > previousFrames + 2 && !/historical/.test(await page.locator('#source').innerText()), 'new connection replaces history');
  check('reconnect resumes new simulated session', /Simulated/.test(await page.locator('#source').innerText()));
  await page.locator('#connect').evaluate(button => button.click());
  check('explicit disconnect retains map', /historical/.test(await page.locator('#source').innerText()));
  await stop(mapper);
  await page.locator('#feed-mode').selectOption('mock');
  await delay(200);
  check('explicit mock selection', /Mock data/.test(await page.locator('#source').innerText()) && await page.locator('#connect').isDisabled());

  console.log('Testing real recording transport: known synthetic and unknown original acquisition.');
  // These are synthetic fixtures even when their header tests unknown legacy metadata.
  const fixture = launch(python, ['-B', '-c', `
import sys
from pathlib import Path
from dataclasses import replace
from lidar_mapper.sim import stream
from lidar_mapper.protocol import encode
from lidar_mapper.server import write_record
frames=list(stream(8))
for name,source in [('synthetic','sim'),('unknown','legacy-unknown'),('real-header','lidar')]:
    with (Path(sys.argv[1])/(name+'.esd')).open('xb') as fh:
        for frame in frames: write_record(fh,encode(replace(frame,source=source)))
`, artifacts]);
  await waitUntil(() => { if (fixture.launchError) throw fixture.launchError; return fixture.exitCode !== null; }, 'recording fixtures');
  if (fixture.exitCode !== 0) throw new Error(fixture.logs);
  await page.locator('#feed-mode').selectOption('sonar');
  for (const name of ['synthetic', 'unknown', 'real-header']) {
    const before = frames;
    await startMapper(['replay', join(artifacts, `${name}.esd`), '--serve']);
    await connect();
    await waitUntil(() => frames > before + 2 && lastFrame.source === 'recorded', `${name} replay frames`);
    const label = await page.locator('#source').innerText();
    const acquisition = name === 'synthetic' ? 'simulated' : name === 'unknown' ? 'recorded' : 'live';
    check(`${name} replay source`, /replay/.test(label) && lastFrame.acquisition_source === acquisition);
    check(`${name} replay not live`, await page.locator('#source').getAttribute('data-live') === null);
    const texts = await planText();
    check(`${name} replay PNG attribution`, texts.some(t => /replay/.test(t)) && (name === 'synthetic'
      ? texts.includes('SIMULATED DATA') : (name !== 'unknown' || texts.some(t => /original acquisition unknown/.test(t))) && !texts.includes('SIMULATED DATA')));
    if (name === 'unknown') await savedSnapshot('unknown', /original acquisition unknown/);
    await disconnectCheck(`${name} replay loss`);
  }
  console.log('Testing live binary delivery of synthetic acquisition and delayed worker results.');
  const beforeLive = frames;
  await startMapper(['serve']);
  await connect();
  const fakePhone = launch(python, ['-u', '-B', '-m', 'lidar_mapper', 'fake-phone', '--frames', '40', '--fps', '5']);
  await waitUntil(async () => frames > beforeLive + 2 && lastFrame.acquisition_source === 'simulated'
    && /map points/.test(await page.locator('#connection-note').innerText()), 'binary phone simulator mounted');
  check('live delivery with simulated acquisition correctly labelled', lastFrame.source === 'live'
    && /Simulated/.test(await page.locator('#source').innerText()) && await page.locator('#source').getAttribute('data-live') === null);
  await page.evaluate(() => { window.__holdMapperResults = true; });
  await waitUntil(() => page.evaluate(() => window.__heldMapperResults.length > 0), 'hold an actual worker response', 30000);
  await page.locator('#connect').evaluate(button => button.click());
  await delay(200);
  const historicalVertices = await page.locator('#vertices').innerText();
  await page.evaluate(() => {
    window.__holdMapperResults = false;
    for (const release of window.__heldMapperResults.splice(0)) release();
  });
  await delay(500);
  check('late worker result cannot replace disconnected historical frame',
    await page.locator('#vertices').innerText() === historicalVertices && /historical/.test(await page.locator('#source').innerText()));
  const historicalText = await planText();
  check('historical trained analysis survives late inference', historicalText.some(t => /historical/.test(t))
    && historicalText.some(t => /LiDAR surface forest v1/.test(t)));
  await connect();
  await waitUntil(async () => !/historical/.test(await page.locator('#source').innerText())
    && /LiDAR surface forest v1/.test(await page.locator('#connection-note').innerText()), 'reconnect with shared trained worker');
  check('shared worker resumes a new adapter session', /Simulated/.test(await page.locator('#source').innerText()));
  await waitUntil(() => { if (fakePhone.launchError) throw fakePhone.launchError; return fakePhone.exitCode !== null; }, 'synthetic publisher complete');
  check('synthetic binary publisher completed', fakePhone.exitCode === 0 && /sent 40 frames/.test(fakePhone.logs));
  await disconnectCheck('binary simulation loss');
  results.workers = workers;
  results.browserErrors = errors;
  check('no browser errors', errors.length === 0);
  await free(8770); check('simulation does not bind phone port', true);
} catch (error) {
  report.error = error.stack; process.exitCode = 1;
} finally {
  await Promise.all(children.slice().reverse().map(stop));
  await Promise.race([browser?.close().catch(() => {}), delay(3000)]);
  await Promise.race([browserServer?.close().catch(() => {}), delay(3000)]);
  report.processLogs = children.filter(p => p.logs !== undefined).map(p => p.logs);
  report.passed = Object.values(assertions).filter(Boolean).length;
  report.failed = Object.values(assertions).filter(ok => !ok).length;
  report.completed = !report.error;
  if (report.failed || report.error) process.exitCode = 1;
  try { for (const port of [4173, 8765, 8770, 8780]) await free(port); report.portsReleased = true; }
  catch (error) { report.portsReleased = false; report.cleanupError = error.message; process.exitCode = 1; }
  await writeFile(join(artifacts, 'report.json'), JSON.stringify(report, null, 2), { flag: 'wx' });
  console.log(JSON.stringify({ ...report, processLogs: undefined }, null, 2));
  console.log(`Report: ${join(artifacts, 'report.json')}`);
}
