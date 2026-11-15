import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { createMapperSession, mapperLabel, readSonarStatus, sonarText } from '../src/mapper-adapter.js';
import { colorsFor } from '../src/room-classifier.js';
import { fixedMapperMessage } from '../scripts/fixtures/mapper-regression.mjs';

const baseline = JSON.parse(await readFile(new URL('../scripts/fixtures/main-86a767c.json', import.meta.url)));
const hash = data => createHash('sha256').update(data).digest('hex');
const typed = data => new Uint8Array(data.buffer, data.byteOffset, data.byteLength);

test('trained labels, colors, geometry and full analysis match original main 86a767c', async () => {
  const frame = await createMapperSession().decode(fixedMapperMessage());
  assert.equal(frame.mapper.analysis.model, baseline.model);
  assert.equal(frame.mapper.mapPoints, baseline.points);
  assert.deepEqual(frame.mapper.analysis.counts, baseline.counts);
  assert.equal(hash(typed(frame.mapper.analysis.labels)), baseline.labels);
  assert.equal(hash(typed(frame.colors)), baseline.colors);
  assert.equal(hash(typed(frame.points)), baseline.geometry);
  assert.equal(hash(JSON.stringify(frame.mapper.analysis)), baseline.analysis);
});

for (const [delivery, acquisition, expected] of [
  ['simulated', 'simulated', 'Simulated LiDAR map'],
  ['live', 'simulated', 'Simulated LiDAR map'],
  ['live', 'live', 'LiDAR map'],
  ['recorded', 'live', 'LiDAR map / replay'],
  ['recorded', 'simulated', 'Simulated LiDAR map / replay'],
  ['recorded', 'recorded', 'LiDAR map / original acquisition unknown / replay'],
]) {
  test(`trained adapter preserves ${delivery}/${acquisition} and matching colors`, async () => {
    const frame = await createMapperSession().decode(fixedMapperMessage({ delivery, acquisition }));
    assert.equal(frame.mapper.delivery, delivery);
    assert.equal(frame.mapper.acquisition, acquisition);
    assert.equal(frame.mapper.simulated, acquisition === 'simulated');
    assert.equal(frame.mapper.stale, false);
    assert.equal(mapperLabel(frame.mapper), expected);
    assert.equal(mapperLabel({ ...frame.mapper, stale: true }), `Last map / historical / ${expected}`);
    assert.equal(hash(typed(frame.mapper.analysis.labels)), baseline.labels);
    assert.deepEqual(frame.colors, colorsFor(frame.mapper.analysis.labels, frame.mapper.mapPoints));
  });
}

test('missing legacy provenance stays unknown; invalid explicit modes are rejected', async () => {
  const raw = JSON.parse(fixedMapperMessage());
  delete raw.source; delete raw.acquisition_source;
  const frame = await createMapperSession().decode(JSON.stringify(raw));
  assert.equal(frame.mapper.delivery, 'recorded');
  assert.equal(frame.mapper.acquisition, 'recorded');
  assert.match(mapperLabel(frame.mapper), /original acquisition unknown.*replay/);
  raw.acquisition_source = 'invented';
  await assert.rejects(createMapperSession().decode(JSON.stringify(raw)), /provenance/);
  assert.match(mapperLabel({ simulated: true, delivery: 'recorded' }), /^Simulated/);
  assert.match(mapperLabel({ simulated: false, delivery: 'recorded' }), /original acquisition unknown/);
});

test('legacy sonar provenance is not inferred from the depth sensor', () => {
  assert.match(sonarText(readSonarStatus({ state: 'agree', range_m: 1, acquisition_source: 'recorded' })),
    /^Recorded sonar \(original acquisition unknown\)/);
});

test('a skipped or reset inference cannot publish its sonar surface or stale analysis', async () => {
  let finish;
  const session = createMapperSession({ classify: () => new Promise(resolve => { finish = resolve; }) });
  const raw = JSON.parse(fixedMapperMessage()); raw.frame.points = [[0, 0, 0, 3]];
  const first = session.decode(JSON.stringify(raw));
  raw.frame.points = [[1, 0, 0, 3], [0.8, 0, 0, 200]];
  raw.frame.meta.sonar = { state: 'sonar_closer', range_m: 0.8, synthetic: true };
  assert.equal(await session.decode(JSON.stringify(raw)), null);
  assert.equal(session.sonarSurface.length, 0);
  session.reset();
  finish({ labels: new Uint8Array(1), objects: [], floorArea: 0, roomHeight: null, model: 'stale fixture' });
  assert.equal(await first, null);
  assert.equal(session.analysis.model, undefined);
  assert.equal(session.sonarSurface.length, 0);
});

test('reconnect sessions isolate out-of-order classifier results and preserve archived reports/markers', async () => {
  const jobs = [];
  const classify = () => new Promise(resolve => jobs.push(resolve));
  const before = createMapperSession({ classify }), after = createMapperSession({ classify });
  const raw = JSON.parse(fixedMapperMessage()); raw.frame.points = [[0, 0, 0, 3], [0.8, 0, 0, 200]];
  const oldFrame = before.decode(JSON.stringify(raw));
  raw.frame.points = [[1, 0, 0, 3], [1.2, 0, 0, 200]];
  const newFrame = after.decode(JSON.stringify(raw));
  const report = model => ({ labels: new Uint8Array([1]), objects: [], floorArea: 1, roomHeight: null, model });
  jobs[1](report('new session'));
  const current = await newFrame;
  jobs[0](report('historical session'));
  const historical = await oldFrame;
  assert.equal(after.analysis, current.mapper.analysis);
  assert.equal(after.analysis.model, 'new session');
  assert.equal(historical.mapper.analysis.model, 'historical session');
  assert.notDeepEqual(current.mapper.sonarSurface, historical.mapper.sonarSurface);
  assert.deepEqual(structuredClone(historical).mapper.sonarSurface, historical.mapper.sonarSurface);
});
