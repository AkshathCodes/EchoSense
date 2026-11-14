export const speedOfSound = 343;
export const pulseSeconds = 0.003;
export const pulseSpacing = 0.38;
export const trialCount = 5;
const minimumRange = 0.65;
const maximumRange = 4.5;

export function makeChirp(sampleRate) {
  const count = Math.round(pulseSeconds * sampleRate);
  return Float32Array.from({ length: count }, (_, index) => {
    const time = index / sampleRate;
    const cycles = 1050 * time + ((4200 - 1050) / (2 * pulseSeconds)) * time ** 2;
    return 0.36 * Math.sin(Math.PI * 2 * cycles) * Math.sin(Math.PI * index / (count - 1)) ** 2;
  });
}

function correlations(recording, reference, start, end, stride) {
  if (start < 0 || end + reference.length > recording.length || end <= start) {
    throw new RangeError("Recording ended before the echo window. Keep the capture tab in the foreground.");
  }
  const result = new Float32Array(end - start);
  for (let offset = start; offset < end; offset += 1) {
    let score = 0;
    for (let index = 0; index < reference.length; index += stride) {
      score += recording[offset + index] * reference[index];
    }
    result[offset - start] = Math.abs(score);
  }
  return result;
}

function largestIndex(samples, start, end) {
  let best = start;
  for (let index = start + 1; index < end; index += 1) {
    if (samples[index] > samples[best]) best = index;
  }
  return best;
}

export function analyzePulse(recording, sampleRate, emittedAt) {
  const chirp = makeChirp(sampleRate);
  const start = emittedAt - Math.round(sampleRate * 0.01);
  const directWindow = Math.round(sampleRate * 0.17);
  const searchNear = Math.ceil(2 * minimumRange * sampleRate / speedOfSound);
  const searchFar = Math.floor(2 * maximumRange * sampleRate / speedOfSound);
  const corr = correlations(recording, chirp, start, start + directWindow + searchFar, 4);
  const loudest = largestIndex(corr, 0, directWindow);
  const noise = Array.from(corr.slice(0, Math.round(sampleRate * 0.008))).sort((left, right) => left - right);
  const noiseFloor = noise[Math.floor(noise.length * 0.9)];
  const directThreshold = Math.max(corr[loudest] * 0.55, noiseFloor * 7, 0.006);
  const directCandidate = corr.findIndex((value, index) => index > 0 && index < directWindow - 1 &&
    value >= directThreshold && value > corr[index - 1] && value >= corr[index + 1]);
  if (directCandidate < 0) return { status: "no_direct", range_m: null, echo_ratio: null };
  const direct = largestIndex(corr, directCandidate,
    Math.min(directWindow, directCandidate + Math.round(sampleRate * 0.0008)));
  const last = direct + searchFar;
  const first = direct + searchNear;
  const clipped = recording.subarray(start + direct, start + last + chirp.length)
    .some((sample) => Math.abs(sample) >= 0.995);
  if (clipped) return { status: "clipped", range_m: null, echo_ratio: null };
  const best = largestIndex(corr, first, last);
  const ratio = corr[best] / corr[direct];
  if (corr[best] < Math.max(corr[direct] * 0.035, noiseFloor * 5)) {
    return { status: "no_echo", range_m: null, echo_ratio: ratio };
  }
  const resolution = Math.round(sampleRate * 0.0015);
  const competing = corr.subarray(first, last).some((value, index) =>
    Math.abs(first + index - best) > resolution && value >= corr[best] * 0.83);
  if (competing) return { status: "ambiguous", range_m: null, echo_ratio: ratio };
  const delay = (best - direct) / sampleRate;
  return { status: "ok", range_m: delay * speedOfSound / 2, echo_ratio: ratio };
}
