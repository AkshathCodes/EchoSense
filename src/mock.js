// The demo generator is independent of the socket transport and its decoder.
export function mockFrame(time) {
  const phase = time / 6500;
  return {
    frame: Math.floor(time / 100),
    latencyMs: Math.round(18 + 3 * Math.sin(phase * 3)),
    target: {
      position: [0.72 + 1.05 * Math.sin(phase), 0.02, 0.28 + 0.7 * Math.cos(phase)],
      confidence: 0.84 + 0.06 * Math.sin(phase * 1.8),
    },
  };
}
