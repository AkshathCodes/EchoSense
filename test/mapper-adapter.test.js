import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createMapperSession, pointSpacing, classifierSteps, MAPPER_MAX_POINTS } from '../src/mapper-adapter.js';
import { decodeSocketFrame } from '../src/sonar.js';
import { simulate } from './scan-simulator.js';
import { WALL, FLOOR, OBJECT } from '../src/room-classifier.js';

// SYNTHETIC fixtures shaped like the Mac mapper's viewer messages (lidar/mapper server.snapshot).
// Mapper axes are X forward, Y left, Z up, so a viewer point [x, y, z] goes out as [-z, -x, y].
function mapperMessage(cloud, { live = [], sequence = 7, hits = null } = {}) {
  const rows = [];
  for (let i = 0; i < cloud.length; i += 3) {
    rows.push([-cloud[i + 2], -cloud[i], cloud[i + 1], Math.min(50, hits?.[i / 3] ?? 5)].map(n => +n.toFixed(3)));
  }
  for (const [x, y, z] of live) rows.push([-z, -x, y, 100]);
  return JSON.stringify({ protocol_version: '0.1', type: 'sonar_frame', sequence, timestamp: 12.5, source: 'live',
    acquisition_source: 'live', detections: null, frame: { format_version: '0.2', points: rows,
      meta: { format_version: '0.2', source: 'live', sensor_id: 'iphone-lidar', tilt_deg: 0, kind: 'lidar_map', view: 'both' } } });
}
/** One point per `size` cube, like the mapper's display thinning. Returns points and their hit counts. */
function thin({ cloud, hits }, size) {
  const seen = new Set(), out = [], kept = [];
  for (let i = 0; i < cloud.length; i += 3) {
    const k = `${Math.floor(cloud[i] / size)},${Math.floor(cloud[i + 1] / size)},${Math.floor(cloud[i + 2] / size)}`;
    if (!seen.has(k)) { seen.add(k); out.push(cloud[i], cloud[i + 1], cloud[i + 2]); kept.push(hits[i / 3]); }
  }
  return { cloud: new Float32Array(out), hits: kept };
}
// Like the mapper, keep only cells seen at least twice, and send their real hit counts.
const scan = (() => {
  const { memory } = simulate({ seconds: 60, outliers: 0.01 });
  const all = memory.cloud(), counts = memory.hits(), cloud = [], hits = [];
  for (let i = 0; i < counts.length; i++) if (counts[i] >= 2) { cloud.push(all[i * 3], all[i * 3 + 1], all[i * 3 + 2]); hits.push(counts[i]); }
  return { cloud: new Float32Array(cloud), hits };
})();
const room = scan.cloud;

test('mapper map frames become classified viewer frames, live points drawn on top', async () => {
  const session = createMapperSession();
  const frame = await session.decode(mapperMessage(room, { hits: scan.hits, live: [[0, 0, -1], [0.1, 0, -1]] }));
  assert.equal(frame.points.length, room.length + 6);
  assert.equal(frame.colors.length, frame.points.length);
  assert.equal(frame.mapper.mapPoints, room.length / 3);
  assert.equal(frame.mapper.livePoints, 2);
  assert.deepEqual([...frame.points.slice(0, 3)].map(n => +n.toFixed(2)), [...room.slice(0, 3)].map(n => +n.toFixed(2)));
  assert.deepEqual([...frame.colors.slice(-3)].map(n => +n.toFixed(2)), [1, 0.36, 0.25]);
  assert.equal(frame.sonar.delivery, 'live');
  const { analysis } = session;
  assert.ok(Math.abs(analysis.floorY + 1.3) < 0.06 && Math.abs(analysis.roomHeight - 2.5) < 0.1);
  assert.ok(analysis.counts[WALL] > analysis.counts[FLOOR] && analysis.counts[OBJECT] > 0);
  for (const [x, z, h] of [[0, -1.55, 0.8], [1.5, 0, 0.75], [-1.55, 1.25, 0.5]]) {
    assert.ok(analysis.objects.some(o => Math.abs(o.center[0] - x) < 0.4 && Math.abs(o.center[1] - z) < 0.4 &&
      Math.abs(o.height - h) < 0.15), `no object near ${x}, ${z}`);
  }
});

for (const size of [0.08, 0.12]) {
  test(`still finds floor, walls and furniture when the map is thinned to ${size * 100} cm`, async () => {
    const { cloud, hits } = thin(scan, size);
    const spacing = pointSpacing(cloud);
    assert.ok(spacing * 1.6 > size * 0.7 && spacing * 1.6 < size * 1.5, `nearest neighbour ${spacing}`);
    const session = createMapperSession();
    await session.decode(mapperMessage(cloud, { hits }));
    const { analysis } = session, total = cloud.length / 3;
    console.log(`thinned ${size}`, JSON.stringify({ points: total, spacing: +spacing.toFixed(3), steps: classifierSteps(spacing).layer,
      wall: +(analysis.counts[WALL] / total).toFixed(2), floor: +(analysis.counts[FLOOR] / total).toFixed(2),
      objects: analysis.objects.map(o => `${o.width.toFixed(1)}x${o.depth.toFixed(1)}x${o.height.toFixed(2)}@${o.center.map(n => n.toFixed(1))}`) }));
    assert.ok(Math.abs(analysis.floorY + 1.3) < 0.12, `floor ${analysis.floorY}`);
    assert.ok(analysis.counts[WALL] / total > 0.35, 'walls mostly lost');
    for (const [x, z] of [[0, -1.55], [1.5, 0]]) {
      assert.ok(analysis.objects.some(o => Math.abs(o.center[0] - x) < 0.5 && Math.abs(o.center[1] - z) < 0.5), `no object near ${x}, ${z}`);
    }
    assert.ok(analysis.objects.length <= 8, `${analysis.objects.length} objects`);
  });
}

test('an unchanged map is not reclassified, a changed one is', async () => {
  const session = createMapperSession();
  await session.decode(mapperMessage(room));
  const first = session.analysis;
  await session.decode(mapperMessage(room, { sequence: 8, live: [[0, 0, -1]] }));
  assert.equal(session.analysis, first);
  await session.decode(mapperMessage(room.subarray(0, room.length - 300), { sequence: 9 }));
  assert.notEqual(session.analysis, first);
  session.reset();
  assert.equal(session.analysis.objects.length, 0);
});

test('other payloads fall through to the sonar decoder, bad mapper frames are rejected', async () => {
  const session = createMapperSession();
  const sonar = JSON.stringify({ protocol_version: '0.1', type: 'sonar_frame', sequence: 1, timestamp: 0, source: 'live',
    acquisition_source: 'simulated', detections: null, frame: { format_version: '0.2', points: [[1, 0, 0, 3]] } });
  assert.equal(await session.decode(sonar), undefined);
  assert.equal((await decodeSocketFrame(sonar)).points.length, 3);
  assert.equal(await session.decode('not json'), undefined);
  const bad = JSON.parse(mapperMessage(room.subarray(0, 30)));
  bad.frame.points[0] = [1, 2, 'x', 4];
  await assert.rejects(session.decode(JSON.stringify(bad)));
  bad.frame.points = Array.from({ length: MAPPER_MAX_POINTS + 1 }, () => [0, 0, 0, 2]);
  await assert.rejects(session.decode(JSON.stringify(bad)));
});

test('sonar status and sonar-only surface points come through, labelled when simulated', async () => {
  const { readSonarStatus, sonarText } = await import('../src/mapper-adapter.js');
  const message = JSON.parse(mapperMessage(room.subarray(0, 3000), { live: [[0, 0, -1]] }));
  message.frame.points.push([0.9, 0.2, 0.1, 200]);          // mapper axes: forward, left, up
  message.frame.meta.sonar = { state: 'sonar_closer', range_m: 0.9, lidar_near_m: 2.41, lidar_median_m: 2.5,
    surface_points: 1, synthetic: true, age_ms: 40 };
  const session = createMapperSession();
  const frame = await session.decode(JSON.stringify(message));
  assert.equal(frame.mapper.mapPoints, 1000);
  assert.equal(frame.mapper.livePoints, 1);
  assert.deepEqual([...session.sonarSurface].map(n => +n.toFixed(2)), [-0.2, 0.1, -0.9]);
  assert.deepEqual([...frame.colors.slice(-3)].map(n => +n.toFixed(2)), [1, 0.25, 0.9]);
  assert.equal(frame.mapper.sonar.blind, true);
  assert.equal(sonarText(frame.mapper.sonar), 'Simulated sonar 0.90 m · LiDAR 2.41 m · surface LiDAR cannot see');
  assert.equal(sonarText(readSonarStatus({ state: 'agree', range_m: 2.4, lidar_near_m: 2.41 })), 'Sonar 2.40 m · LiDAR 2.41 m · agree');
  assert.equal(sonarText(readSonarStatus({ state: 'no_sonar', range_m: null, lidar_near_m: null })), 'Sonar no echo · LiDAR no return · no fresh reading');
  assert.equal(readSonarStatus({ state: 'made_up' }), null);
  assert.equal(readSonarStatus(undefined), null);
  const plain = await createMapperSession().decode(mapperMessage(room.subarray(0, 3000)));
  assert.equal(plain.mapper.sonar, null);
});
