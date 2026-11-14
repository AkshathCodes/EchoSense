# ADR-0008: Noise-aware (CFAR-style) threshold for point extraction

- **Status:** accepted; defaults amended by [ADR-0010](0010-simulator-realism-v2.md) (relative threshold -30 → -50 dB; the noise floor is now absolute)
- **Date:** 2026-11-14
- **Area:** perception

## Context
Points were extracted with a single threshold relative to the frame's peak
(-30 dB). In noisy frames (heavy smoke preset, noise floor -35 dB) about 7% of
all voxels passed, giving ~23k false points per frame and thousands of junk
clusters. See [log §9](../log/2026-11-13-ideation-and-research.md).

## Decision
`threshold = max(peak · 10^(point_threshold_db/20), median(volume) · 10^(noise_margin_db/20))`
with defaults -30 dB and +15 dB (`SensorConfig`). The median estimates the
noise floor because most voxels hold no echo.

## Alternatives considered
- Fixed relative threshold only: fails under noise (above).
- Proper local CFAR (cell-averaging per range ring): better under range-varying
  noise and clutter; **do this when real data arrives**.

## Consequences
Noise clusters across 400 scenes dropped from 6,131 to 3; baseline accuracy in
heavy conditions rose from 0.75 to 0.83. Weak real echoes in very noisy frames
can now be suppressed. That's a tradeoff to re-tune on real captures.
