import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createSpatialMemory, SEEN, SURFACE } from '../src/spatial-memory.js';
import { createLidarSession, lidarLabel } from '../src/lidar.js';
import { createCues, cueNames } from '../src/audio-cues.js';

// SYNTHETIC fixtures. None of this is real sensor data.
const pose = (x, y, z) => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1];
const message = (changes = {}) => JSON.stringify({ type: 'lidar_frame', schema_version: 1, session_id: 's1',
  device_id: 'fixture', sequence: 0, timestamp: 1, source: 'synthetic', coordinate_frame: 'arkit_world',
  units: 'meters', tracking: 'normal', camera_to_world: pose(0, 0, 0),
  points: [[0, 0, -2], [0.01, 0.01, -1.99], [1, -1.3, -1]], confidences: [2, 2, 2], ...changes });
const cells = memory => { const out = new Map(); memory.eachCell((x, z, s) => out.set(`${x},${z}`, s)); return out; };

test('voxel filter keeps one point per cell and respects the retention cap', () => {
  const memory = createSpatialMemory({ voxel: 0.05, maxVoxels: 3 });
  memory.addFrame({ points: [[0, 0, -2], [0.01, 0.01, -1.99], [1, 0, -2], [2, 0, -2], [3, 0, -2]],
    confidences: [2, 2, 2, 2, 2], camera: [0, 0, 0], tracking: 'normal' });
  assert.equal(memory.count, 3);
  assert.equal(memory.stats().dropped, 1);
  assert.deepEqual([...memory.cloud()].slice(0, 3).map(n => +n.toFixed(2)), [0, 0, -2]);
});

test('low-confidence points and untracked frames are not stored', () => {
  const memory = createSpatialMemory({ minConfidence: 1 });
  memory.addFrame({ points: [[0, 0, -1], [1, 0, -1]], confidences: [0, 2], camera: [0, 0, 0], tracking: 'normal' });
  assert.equal(memory.count, 1);
  const result = memory.addFrame({ points: [[5, 0, -1]], confidences: [2], camera: [9, 0, 0], tracking: 'limited' });
  assert.equal(result.stored, false);
  assert.equal(memory.count, 1);
  assert.equal(memory.trajectory.length, 1);
  assert.equal(memory.stats().framesSkipped, 1);
});

test('coverage separates surface, seen-through and unknown cells', () => {
  const memory = createSpatialMemory({ cell: 0.25, raySubsample: 1 });
  // A floor return first sets floor level, then a wall return 2 m ahead at scanner height.
  memory.addFrame({ points: [[0, -1.3, -0.5], [0.1, 0, -2.1]], confidences: [2, 2],
    camera: [0.1, 0, -0.1], tracking: 'normal' });
  const map = cells(memory);
  assert.equal(map.get('0,-9'), SURFACE);           // z = -2.1 falls in cell -9
  assert.equal(map.get('0,-5'), SEEN);              // ray crossed it
  assert.equal(map.get('0,-2'), SEEN);              // floor return: seen, not an obstacle
  assert.equal(map.get('0,-12'), undefined);        // behind the wall: unknown
  assert.equal(map.get('4,-4'), undefined);         // off to the side: unknown
  const stats = memory.stats();
  assert.equal(stats.cellsSurface, 1);
  assert.equal(stats.observedArea, (stats.cellsSeen + 1) * 0.0625);
});

test('trajectory records movement and path length, and clear forgets everything', () => {
  const memory = createSpatialMemory();
  for (const x of [0, 0.01, 1, 2]) memory.addFrame({ points: [], confidences: [], camera: [x, 0, 0], tracking: 'normal' });
  assert.equal(memory.trajectory.length, 3);        // the 1 cm step is ignored
  assert.equal(+memory.stats().pathMeters.toFixed(2), 2);
  memory.clear();
  assert.equal(memory.count + memory.trajectory.length + memory.stats().cellsSeen, 0);
});

test('session decodes frames, accumulates across them and lifts the floor to y = 0', async () => {
  const events = [];
  const session = createLidarSession({ onEvent: name => events.push(name) });
  const first = await session.decode(message());
  assert.equal(first.points.length, 6);             // two of three points share a voxel
  assert.equal(first.lidar.simulated, true);
  assert.equal(lidarLabel(first.lidar), 'Simulated LiDAR');
  assert.equal(+first.target.position[1].toFixed(2), 1.3);        // scanner 1.3 m above lowest point
  assert.ok(Math.abs(Math.min(...[...first.points].filter((_, i) => i % 3 === 1))) < 1e-6);
  const second = await session.decode(message({ sequence: 1, camera_to_world: pose(1, 0, 0),
    points: [[3, 0, -2]], confidences: [2] }));
  assert.equal(second.points.length, 9);            // earlier geometry is still there
  assert.equal(second.lidar.trail.length, 2);
  assert.deepEqual(events, ['session_started']);
});

test('tracking loss, recovery, new sessions and bridge status raise events', async () => {
  const events = [];
  const session = createLidarSession({ onEvent: name => events.push(name) });
  await session.decode(message());
  const lost = await session.decode(message({ sequence: 1, tracking: 'limited', points: [[9, 0, 0]], confidences: [2] }));
  assert.equal(lost.points.length, 6);              // nothing stored while tracking is limited
  await session.decode(message({ sequence: 2 }));
  const fresh = await session.decode(message({ session_id: 's2', points: [[0, 0, -1]], confidences: [2] }));
  assert.equal(fresh.points.length, 3);             // the old origin's map is not merged
  await session.decode('{"type":"lidar_status","schema_version":1,"mode":"live","publisher_connected":true}');
  const replay = await session.decode('{"type":"lidar_status","schema_version":1,"mode":"replay","publisher_connected":false}');
  assert.equal(lidarLabel(replay.lidar), 'Simulated LiDAR replay');
  assert.deepEqual(events, ['session_started', 'tracking_lost', 'tracking_restored', 'session_started', 'publisher_connected']);
});

test('pause freezes the map, clear empties it, other messages fall through', async () => {
  const session = createLidarSession();
  await session.decode(message());
  session.setPaused(true);
  const paused = await session.decode(message({ sequence: 1, points: [[4, 0, 0]], confidences: [2] }));
  assert.equal(paused.points, undefined);
  assert.equal(session.memory.count, 2);
  session.clear();
  assert.equal(session.current().points.length, 0);
  assert.equal(await session.decode('{"protocol_version":"0.1","type":"sonar_frame"}'), undefined);
});

test('malformed LiDAR frames are rejected', async () => {
  const session = createLidarSession();
  for (const bad of [{ schema_version: 2 }, { units: 'feet' }, { coordinate_frame: 'sonar' }, { confidences: [2] },
    { points: [[0, 0]], confidences: [2] }, { points: [[0, 0, 1e9]], confidences: [2] }, { tracking: 'fine' },
    { camera_to_world: [1, 2, 3] }, { source: 'sonar' }, { session_id: '' }]) {
    await assert.rejects(session.decode(message(bad)), `accepted ${JSON.stringify(bad)}`);
  }
});

test('audio cues are off by default, distinct, and rate limited', () => {
  const tones = [];
  const node = () => ({ frequency: {}, gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} },
    connect(next) { return next; }, start() {}, stop() {} });
  const cues = createCues({ context: () => ({ currentTime: 0, destination: {}, resume() {},
    createOscillator() { const tone = node(); tones.push(tone); return tone; }, createGain: node }) });
  assert.equal(cues.play('tracking_lost', 0), false);
  cues.setEnabled(true);
  assert.equal(cues.play('tracking_lost', 0), true);
  assert.equal(cues.play('tracking_lost', 500), false);
  assert.equal(cues.play('tracking_lost', 2000), true);
  assert.equal(cues.play('no_such_cue', 0), false);
  assert.equal(tones.length, 4);
  assert.ok(cueNames.includes('scan_saved') && cueNames.includes('session_started'));
});

test('decodes the exact text the iPhone app writes', async () => {
  // Mirrors WireFormat.message in ios-lidar/EchoSenseLiDAR/ScanPoint.swift. A fixture, not a capture.
  const text = '{"type":"lidar_frame","schema_version":1,"session_id":"0B6F2C1E-5D0A-4C55-9E0B-0C2E5B3D9A11",' +
    '"device_id":"iphone-1A2B3C4D","sequence":12,"timestamp":51234.567,"source":"arkit_scene_depth",' +
    '"coordinate_frame":"arkit_world","units":"meters","tracking":"normal",' +
    '"camera_to_world":[0.99985,0.00000,-0.01745,0.00000,0.00000,1.00000,0.00000,0.00000,' +
    '0.01745,0.00000,0.99985,0.00000,0.512,-0.031,-1.204,1.00000],' +
    '"points":[[0.500,-1.200,-2.003],[-0.041,0.007,-0.950]],"confidences":[2,1]}';
  const frame = await createLidarSession().decode(text);
  assert.equal(frame.points.length, 6);
  assert.equal(frame.lidar.simulated, false);
  assert.equal(lidarLabel(frame.lidar), 'Live LiDAR');
  assert.equal(+frame.target.position[0].toFixed(3), 0.512);
});
