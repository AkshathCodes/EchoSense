import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { decodeRelayLidar, lidarLabel, createLidarMap, readLidarReplay } from '../src/lidar.js';

const relay = {
  type: 'sonar_frame', protocol_version: '0.1', sequence: 1, timestamp: 12.25,
  source: 'live', acquisition_source: 'live', detections: null,
  frame: { format_version: '0.2', points: [[2, 3, 4, 2], [1, 2, 3, 1]],
    meta: { modality: 'lidar', reference: 'world', tracking: 'normal', sensor_id: 'FAKE-phone-sweep' } },
};

test('the branch relay decodes metric coordinates and labels the fake publisher synthetic', async () => {
  const frame = await decodeRelayLidar(JSON.stringify(relay));
  assert.deepEqual([...frame.points], [-3, 4, -2, -2, 3, -1]);
  assert.equal(frame.lidar.depthConfidence, 1.5);
  assert.equal(frame.lidar.scanner, undefined);
  assert.equal(lidarLabel(frame.lidar), 'Synthetic LiDAR · controlled demo');
});

test('the LiDAR decoder rejects sonar and invalid depth confidence', async () => {
  for (const frame of [
    { ...relay.frame, meta: { ...relay.frame.meta, modality: 'sonar' } },
    { ...relay.frame, points: [[1, 2, 3, 3]] },
  ]) await assert.rejects(decodeRelayLidar(JSON.stringify({ ...relay, frame })));
});

const observation = (seq, points, metadata = {}) => ({
  points: new Float32Array(points), frame: seq, captureTime: seq,
  lidar: { sessionId: 'session-a', deviceId: 'phone', reference: 'world', acquisition: 'simulated',
    tracking: 'normal', scanner: [seq, 1, 0], ...metadata },
});

test('a trusted world session retains distinct observations and tracks camera movement', () => {
  const map = createLidarMap();
  map.observe(observation(0, [0, 0, 0]));
  const scene = map.observe(observation(1, [0, 0, 0, 2, 0, 0]));
  assert.deepEqual([...scene.points], [0, 0, 0, 2, 0, 0]);
  assert.deepEqual(scene.lidar.path, [[0, 1, 0], [1, 1, 0]]);
});

test('a tracking gap leaves a path break and a new origin starts a new map', () => {
  const map = createLidarMap();
  map.observe(observation(0, [0, 0, 0]));
  const limited = map.observe(observation(1, [3, 0, 0], { tracking: 'limited' }));
  assert.deepEqual([...limited.points], [0, 0, 0]);
  assert.equal(limited.lidar.scanner, null);
  const resumed = map.observe(observation(2, [2, 0, 0]));
  assert.deepEqual(resumed.lidar.path, [[0, 1, 0], null, [2, 1, 0]]);
  const reset = map.observe(observation(0, [5, 0, 0], { sessionId: 'session-b' }));
  assert.deepEqual([...reset.points], [5, 0, 0]);
  assert.deepEqual(reset.lidar.path, [[0, 1, 0]]);
});

test('unkeyed relay snapshots replace observations and never invent a trajectory', () => {
  const map = createLidarMap();
  const legacy = { sessionId: undefined, scanner: undefined };
  map.observe(observation(0, [1, 0, 0], legacy));
  const next = map.observe(observation(1, [3, 0, 0], legacy));
  assert.deepEqual([...next.points], [3, 0, 0]);
  assert.deepEqual(next.lidar.path, []);
});

test('a capped session retains recent distinct points and ignores an older sequence', () => {
  const map = createLidarMap(2);
  map.observe(observation(0, [0, 0, 0, 1, 0, 0]));
  assert.deepEqual([...map.observe(observation(2, [2, 0, 0])).points], [1, 0, 0, 2, 0, 0]);
  assert.equal(map.observe(observation(1, [3, 0, 0])), null);
});

test('JSONL playback preserves capture order, timing and synthetic provenance', async () => {
  const second = { ...relay, timestamp: 12.75, sequence: 2 };
  const scan = await readLidarReplay([relay, second].map(row => JSON.stringify(row)).join('\n'));
  assert.deepEqual(scan.history.map(frame => frame.t), [0, 500]);
  assert.equal(scan.lidar.delivery, 'recorded');
  assert.equal(lidarLabel(scan.lidar), 'Synthetic LiDAR replay');
});

test('the synthetic Room map demo preserves the wall when it adds the obstacle', async () => {
  const file = new URL('./fixtures/lidar-room-synthetic.jsonl', import.meta.url);
  const scan = await readLidarReplay(await readFile(file, 'utf8'));
  assert.deepEqual(scan.history.map(frame => [frame.t, frame.points.length / 3]), [[0, 156], [2000, 276], [4000, 325]]);
  assert.deepEqual(scan.points.slice(0, scan.history[0].points.length), scan.history[0].points);
  assert.equal(lidarLabel(scan.lidar), 'Synthetic LiDAR replay');
});
