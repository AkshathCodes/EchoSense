import { test } from 'node:test';
import assert from 'node:assert/strict';
import { comparable, compareReturns, sampleAt, sampleHistory } from '../src/archive.js';

test('change overlay requires a shared coordinate frame', () => {
  assert.equal(comparable({ space: 'demo' }, { space: 'other' }), false);
  assert.equal(comparable({ space: 'demo' }, { space: 'demo' }), true);
  assert.equal(comparable({}, {}), false);
});

test('compare highlights returns newly observed in the same spatial cells', () => {
  const a = new Float32Array([0.10, 1, 0, 4, 1, 0]);
  const b = new Float32Array([0.12, 1, 0, 2, 1, 0, 2.02, 1, 0]);
  assert.deepEqual(Array.from(compareReturns(a, b)), [2, 1, 0, b[6], 1, 0]);
});

test('history preserves gaps and finds the most recent sample at the playhead', () => {
  const samples = [{ t: 10, target: { confidence: 0.8 } }, { t: 20, target: null }];
  assert.equal(sampleAt(samples, 2), undefined);
  assert.equal(sampleAt(samples, 18), samples[0]);
  assert.equal(sampleAt(samples, 20).target, null);
  for (let i = 0; i < 20; i++) sampleHistory(samples, { t: i * 1000 + 1000 });
  assert.equal(samples.length, 12);
  assert.equal(samples.at(-1).t, 20000);
});
