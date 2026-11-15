import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decodeSocketFrame, sonarLabel } from '../src/sonar.js';

const message = {
  protocol_version: '0.1', type: 'sonar_frame', sequence: 7, timestamp: 0.7,
  source: 'recorded', acquisition_source: 'simulated',
  frame: { format_version: '0.2', points: [[2, 3, 4, 17]] },
  detections: { format_version: '0.1', detections: [
    { class: 'wall', confidence: 1, centroid: [2, 0, 0] },
    { class: 'person', confidence: 0.7, centroid: [3, -1, 1] },
    { class: 'person', confidence: 0.9, centroid: [2, 3, 4] },
  ] },
};

test('bridge coordinates, SNR, provenance and strongest person decode together', async () => {
  const result = await decodeSocketFrame(JSON.stringify(message));
  assert.deepEqual([...result.points], [-3, 4, -2]);
  assert.deepEqual(result.target, { position: [-3, 4, -2], confidence: 0.9 });
  assert.equal(result.frame, 7);
  assert.equal(result.captureTime, 0.7);
  assert.equal(result.snr, 17);
  assert.equal(sonarLabel(result.sonar), 'Sonar replay · simulated');
});

test('missing detections and empty point arrays clear the previous readings', async () => {
  const result = await decodeSocketFrame(JSON.stringify({ ...message,
    frame: { format_version: '0.2', points: [] }, detections: null }));
  assert.equal(result.target, null);
  assert.equal(result.points.length, 0);
  assert.equal(result.snr, null);
});

test('rejects incompatible bridge versions and invalid points, accepts preview fixtures', async () => {
  await assert.rejects(decodeSocketFrame(JSON.stringify({ ...message, protocol_version: '9' })), /version/);
  await assert.rejects(decodeSocketFrame(JSON.stringify({ ...message,
    frame: { format_version: '0.2', points: [[2, 3, 4, -1]] } })), /point/);
  const preview = await decodeSocketFrame('{"points":[[1,2,3]]}');
  assert.deepEqual([...preview.points], [1, 2, 3]);
});

test('LiDAR frames from the phone relay carry their modality and reference frame', async () => {
  const result = await decodeSocketFrame(JSON.stringify({ ...message, source: 'live', acquisition_source: 'live',
    frame: { format_version: '0.2', points: [[1.5, 0.5, -0.2, 2], [1.5, -0.5, -0.2, 1]],
      meta: { modality: 'lidar', reference: 'world', tracking: 'normal' } }, detections: null }));
  assert.deepEqual([...result.points].map(n => +n.toFixed(2)), [-0.5, -0.2, -1.5, 0.5, -0.2, -1.5]);
  assert.equal(result.snr, 1.5);
  assert.equal(result.sonar.modality, 'lidar');
  assert.equal(result.sonar.reference, 'world');
  assert.equal(sonarLabel(result.sonar), 'Live LiDAR');
  const sonar = await decodeSocketFrame(JSON.stringify(message));
  assert.equal(sonar.sonar.modality, 'sonar');
});
