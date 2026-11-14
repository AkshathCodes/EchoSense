import { analyzePulse, directSearchSeconds, makeChirp, pulseSpacing, trialCount } from "./audio.mjs";

export async function openRecorder() {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("Microphone capture requires a secure origin. Open localhost on the scanning laptop.");
  }
  const context = new AudioContext();
  let stream;
  try {
    await context.resume();
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
    });
    await context.audioWorklet.addModule("./recorder.js");
    const input = context.createMediaStreamSource(stream);
    const worklet = new AudioWorkletNode(context, "echo-recorder");
    const mute = context.createGain();
    mute.gain.value = 0;
    input.connect(worklet).connect(mute).connect(context.destination);
    return { context, stream, worklet };
  } catch (error) {
    stream?.getTracks().forEach((track) => track.stop());
    await context.close();
    throw error;
  }
}

export async function captureTrials({ context, worklet }) {
  const rate = context.sampleRate;
  const first = Math.ceil((context.currentTime + 0.25) * rate);
  const step = Math.round(pulseSpacing * rate);
  const padding = Math.round(0.08 * rate);
  const start = first - padding;
  const end = first + (trialCount - 1) * step + Math.round((directSearchSeconds + 0.05) * rate);
  const recording = new Float32Array(end - start);
  const populated = new Uint8Array(recording.length);
  const original = makeChirp(rate);
  const pulse = context.createBuffer(1, original.length, rate);
  pulse.copyToChannel(original, 0);
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      worklet.port.onmessage = null;
      reject(new Error("Timed out waiting for audio samples. Check the input device and keep this tab active."));
    }, 5000);
    worklet.port.onmessage = ({ data }) => {
      const chunkEnd = data.start + data.samples.length;
      const from = Math.max(start, data.start);
      const to = Math.min(end, chunkEnd);
      if (to > from) {
        recording.set(data.samples.subarray(from - data.start, to - data.start), from - start);
        populated.fill(1, from - start, to - start);
      }
      if (chunkEnd >= end) {
        clearTimeout(timeout);
        worklet.port.onmessage = null;
        resolve();
      }
    };
    for (let index = 0; index < trialCount; index += 1) {
      const source = context.createBufferSource();
      source.buffer = pulse;
      source.connect(context.destination);
      source.start((first + index * step) / rate);
    }
  });
  if (populated.includes(0)) throw new Error("The microphone stream dropped audio samples. Repeat this scan.");
  const results = Array.from({ length: trialCount }, (_, index) =>
    analyzePulse(recording, rate, padding + index * step));
  return { results, recording, rate };
}

export function toWave(recording, rate) {
  const dataLength = recording.length * 2;
  const bytes = new ArrayBuffer(44 + dataLength);
  const view = new DataView(bytes);
  function writeText(offset, label) {
    [...label].forEach((letter, index) => view.setUint8(offset + index, letter.charCodeAt(0)));
  }
  writeText(0, "RIFF");
  view.setUint32(4, dataLength + 36, true);
  writeText(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(36, "data");
  view.setUint32(40, dataLength, true);
  recording.forEach((sample, index) => {
    view.setInt16(44 + 2 * index, Math.round(Math.max(-1, Math.min(1, sample)) * 32767), true);
  });
  return new Blob([bytes], { type: "audio/wav" });
}
