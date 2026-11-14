import assert from "node:assert/strict";
import { test } from "node:test";
import { analyzePulse, makeChirp, speedOfSound } from "./audio.mjs";
import { parseRangeTrials, previewReport } from "./map.mjs";
import { readSerialBatch } from "./capture.mjs";

test("external distances and misses feed the same pose aggregation", () => {
  const results = parseRangeTrials("1.01\r\ntimeout\r\n0.99\r\n1.02\r\ntimeout");
  const trials = results.map((result, index) => ({
    ...result, trial: index + 1, source: "measured", scene: "Panel", station_m: 0,
    reference_m: 1, height_m: 1, depth_m: 0, heading_deg: 0, pitch_deg: 0, surface: "Panel",
  }));
  const point = previewReport(trials).points[0];
  assert.equal(results[1].status, "no_echo");
  assert.equal(point.accepted, 3);
  assert.equal(point.total, 5);
  assert.equal(point.range_m, 1.01);
  assert.throws(() => parseRangeTrials("1\n1\n1\n1"), /Enter 5 readings/);
  assert.throws(() => parseRangeTrials("1\n1\n150 cm\n1\n1"), /Reading 3/);
});

test("laptop detector can recover an echo after a 192 ms capture delay", () => {
  const rate = 48000;
  const emittedAt = Math.round(0.08 * rate);
  const direct = emittedAt + Math.round(0.192 * rate);
  const chirp = makeChirp(rate);
  for (const meters of [1, 2]) {
    const recording = new Float32Array(Math.round(rate * 0.41));
    const reflected = direct + Math.round(2 * meters * rate / speedOfSound);
    chirp.forEach((sample, index) => {
      recording[direct + index] += sample;
      recording[reflected + index] += 0.24 * sample;
    });
    const result = analyzePulse(recording, rate, emittedAt);
    assert.equal(result.status, "ok");
    assert.ok(Math.abs(result.range_m - meters) < 0.01);
  }
});

test("USB batch reads five complete records across byte chunks and releases the port", async () => {
  const encoder = new TextEncoder();
  const chunks = ["1.", "02\r\ntime", "out\r\n0.98\n1", ".00\n1.01\n9.99\n"];
  const readable = new ReadableStream({
    start(controller) {
      for (const part of chunks) controller.enqueue(encoder.encode(part));
      controller.close();
    },
  });
  let closed = false;
  const port = {
    readable,
    async open(options) { assert.deepEqual(options, { baudRate: 9600 }); },
    async close() { assert.equal(readable.locked, false); closed = true; },
  };
  const results = parseRangeTrials(await readSerialBatch(port, 9600, 1000));
  assert.deepEqual(results.map((result) => result.range_m), [1.02, null, 0.98, 1, 1.01]);
  assert.equal(closed, true);
});

test("USB timeout releases the port and rejects the partial scan", async () => {
  const readable = new ReadableStream();
  let closed = false;
  const port = {
    readable,
    async open() {},
    async close() { assert.equal(readable.locked, false); closed = true; },
  };
  await assert.rejects(readSerialBatch(port, 9600, 15), /timed out after 0 of 5/);
  assert.equal(closed, true);
});
