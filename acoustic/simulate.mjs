import { writeFileSync } from "node:fs";
import { analyzePulse, makeChirp, speedOfSound, trialCount } from "./audio.mjs";

const rate = 48000;
const emittedAt = 4800;
const direct = emittedAt + 1433;
const chirp = makeChirp(rate);

function simulateTrial(distance, amplitude, secondEcho, seed) {
  let random = seed;
  const recording = Float32Array.from({ length: rate / 2 }, () => {
    random = (Math.imul(1664525, random) + 1013904223) >>> 0;
    return (random / 4294967296 - 0.5) * 0.018;
  });
  function add(offset, gain) {
    chirp.forEach((sample, index) => { recording[offset + index] += sample * gain; });
  }
  add(direct, 1);
  add(direct + Math.round(2 * distance * rate / speedOfSound), amplitude);
  if (secondEcho) add(direct + Math.round(2 * 2.55 * rate / speedOfSound), amplitude);
  return analyzePulse(recording, rate, emittedAt);
}

if (!process.argv[2]) throw new Error("Pass the target CSV path as the first argument.");
const lines = ["source,scene,station_m,depth_m,height_m,heading_deg,pitch_deg,surface,reference_m,trial,status,range_m,echo_ratio"];
for (const [scene, reference] of [["Panel at 1 m", 1], ["Panel at 2 m", 2]]) {
  for (const [station, offset] of [[0, 0.01], [0.55, -0.035], [1.1, 0.055]]) {
    for (let index = 0; index < trialCount; index += 1) {
      const noisy = scene === "Panel at 2 m" && station === 1.1 && index < 3;
      const trial = simulateTrial(reference + offset + (index - 2) * 0.012, 0.24, noisy, index + 7);
      if (noisy && trial.status !== "ambiguous") throw new Error("Expected the competing reflection to be rejected.");
      if (!noisy && (trial.status !== "ok" || Math.abs(trial.range_m - reference - offset) > 0.08)) {
        throw new Error(`Unexpected echo estimate: ${JSON.stringify(trial)}`);
      }
      lines.push(["simulated", scene, station, 0, 1, 0, 0, "", reference,
        index + 1, trial.status, trial.range_m, trial.echo_ratio].join(","));
    }
  }
}
const surfaces = [
  { name: "Back wall", poses: [0.2, 0.95, 1.7].flatMap((x) =>
    [0.6, 1.55].map((height) => [x, 0.25, height, 0, 0, 2.35])) },
  { name: "Right wall", poses: [0.55, 1.35, 2.15].flatMap((z) =>
    [0.6, 1.55].map((height) => [0.5, z, height, 90, 0, 1.8])) },
  { name: "Low obstacle", poses: [0.2, 0.65].flatMap((x) =>
    [0.35, 0.8].map((height) => [x, 0, height, 0, 0, 1.15])) },
];
for (let index = 0; index < trialCount; index += 1) {
  const trial = simulateTrial(2.85, index < 2 ? 0.24 : 0, false, index + 29);
  const expectedStatus = index < 2 ? "ok" : "no_echo";
  if (trial.status !== expectedStatus) throw new Error(`Unexpected panel-removed result: ${trial.status}`);
  lines.push(["simulated", "Panel removed", 0, 0, 1, 0, 0, "Background", null, index + 1,
    trial.status, trial.range_m, trial.echo_ratio].join(","));
}
for (const { name, poses } of surfaces) {
  for (const [x, z, height, heading, pitch, reference] of poses) {
    for (let index = 0; index < trialCount; index += 1) {
      const trial = simulateTrial(reference + (index - 2) * 0.009, 0.24, false, index + 29);
      if (trial.status !== "ok") throw new Error(`Unexpected ${name} estimate: ${trial.status}`);
      lines.push(["simulated", "Sample room", x, z, height, heading, pitch, name, reference, index + 1,
        trial.status, trial.range_m, trial.echo_ratio].join(","));
    }
  }
}
writeFileSync(process.argv[2], lines.join("\n") + "\n");
