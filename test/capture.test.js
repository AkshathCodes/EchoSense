import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createMapperSession, mapperLabel, readCaptureStatus, captureText } from '../src/mapper-adapter.js';
import { fixedMapperMessage } from '../scripts/fixtures/mapper-regression.mjs';

test('capture stalls and resumes without reclassifying or losing map/report/markers', async () => {
  const session = createMapperSession();
  const raw = JSON.parse(fixedMapperMessage());
  raw.frame.points.push([0.8, 0, 0, 200]);
  raw.frame.meta.sonar = { state: 'sonar_closer', range_m: 0.8, synthetic: true };
  raw.frame.meta.capture = { mode: 'live', state: 'active', age_s: 0, stall_after_s: 3 };
  const first = await session.decode(JSON.stringify(raw));
  for (const state of ['stalled', 'disconnected', 'complete', 'active']) {
    raw.sequence++;
    raw.frame.meta.capture.state = state;
    raw.frame.meta.capture.age_s = state === 'active' ? 0 : 4;
    const next = await session.decode(JSON.stringify(raw));
    assert.equal(next.mapper.analysis, first.mapper.analysis);
    assert.deepEqual(next.points, first.points);
    assert.deepEqual(next.colors, first.colors);
    assert.deepEqual(next.mapper.sonarSurface, first.mapper.sonarSurface);
    assert.equal(next.mapper.sonar.range, 0.8);
    assert.equal(next.mapper.stale, state !== 'active');
    assert.equal(/historical/.test(mapperLabel(next.mapper)), state !== 'active');
    assert.equal(next.mapper.acquisition, 'simulated'); // Capture status cannot override provenance.
  }
});

test('simulated/replayed capture text and legacy unknown freshness stay explicit', () => {
  const capture = { mode: 'simulated', state: 'complete', age_s: 0.2, stall_after_s: 3 };
  assert.match(captureText(readCaptureStatus(capture)), /^Simulated capture: complete/);
  assert.match(captureText({ ...capture, mode: 'replay' }), /^Replay: complete/);
  assert.equal(readCaptureStatus(undefined), null);
  assert.equal(readCaptureStatus({ ...capture, age_s: -1 }), null);
  assert.equal(readCaptureStatus({ ...capture, state: 'invented' }), null);
  assert.equal(readCaptureStatus({ ...capture, stall_after_s: Infinity }), null);
  assert.equal(captureText(null), 'Capture freshness unavailable');
});
