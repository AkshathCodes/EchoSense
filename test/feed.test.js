import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readPreview, openFeed } from '../src/feed.js';

test('normal bridge EOF is distinct from a network failure', () => {
  const socket = new EventTarget();
  const statuses = [];
  openFeed('ws://localhost:8765/ws', {
    transport: () => socket, decode: JSON.parse, onFrame() {},
    onStatus: value => statuses.push(value),
  });
  socket.dispatchEvent(new Event('open'));
  socket.dispatchEvent(Object.assign(new Event('close'), { code: 1000, reason: 'source complete' }));
  assert.deepEqual(statuses, ['connecting', 'connected', 'complete']);
});

test('preview data becomes geometry and a current estimate', () => {
  const data = readPreview(JSON.stringify({
    points: [[1, 2, 3], [4, 0, -1]], frame: 7,
    target: { position: [2, 1, 0], confidence: 0.72 },
  }));
  assert.deepEqual([...data.points], [1, 2, 3, 4, 0, -1]);
  assert.equal(data.target.confidence, 0.72);
  assert.equal(data.frame, 7);
});

test('preview rejects malformed coordinates and oversized buffers', () => {
  assert.throws(() => readPreview('{"points":[[1,2,"3"]]}'));
  assert.throws(() => readPreview(JSON.stringify({ points: Array(100001).fill([0, 0, 0]) })));
});

test('socket adapter accepts a supplied decoder and ignores events after disconnect', async () => {
  class TestSocket extends EventTarget {
    close() { this.closed = true; }
  }
  const socket = new TestSocket();
  const received = [], statuses = [];
  const stop = openFeed('ws://localhost:9000', {
    transport: () => socket,
    decode: data => ({ reading: Number(data) }),
    onFrame: data => received.push(data),
    onStatus: status => statuses.push(status),
  });
  socket.dispatchEvent(new Event('open'));
  socket.dispatchEvent(new MessageEvent('message', { data: '42' }));
  await new Promise(resolve => setImmediate(resolve));
  stop();
  socket.dispatchEvent(new MessageEvent('message', { data: '43' }));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(received, [{ reading: 42 }]);
  assert.deepEqual(statuses, ['connecting', 'connected', 'disconnected']);
  assert.equal(socket.closed, true);
});

test('a skipped frame does not overtake an earlier frame still being decoded', async () => {
  const socket = new EventTarget(), received = [];
  let finish;
  openFeed('ws://localhost:9000', {
    transport: () => socket,
    decode: data => data === 'skip' ? null : new Promise(resolve => { finish = resolve; }),
    onFrame: frame => received.push(frame),
    onStatus() {},
  });
  socket.dispatchEvent(new MessageEvent('message', { data: 'map' }));
  socket.dispatchEvent(new MessageEvent('message', { data: 'skip' }));
  await new Promise(resolve => setImmediate(resolve));
  finish({ frame: 1 });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(received, [{ frame: 1 }]);
});
