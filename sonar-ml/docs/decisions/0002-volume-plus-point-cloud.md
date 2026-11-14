# ADR-0002: Carry both an intensity volume and a point cloud

- **Status:** accepted (supersedes the earlier plan of point-cloud-only)
- **Date:** 2026-11-14
- **Area:** perception

## Context
The first plan (2026-11-13) made a point cloud the only interface. Research
showed published in-air sonar ML used denser data: Antwerp classified
time-frequency echo images; Liu et al. (Calyo) ran a volumetric 3D U-Net.
Thresholding a beamformed volume into points throws away weak returns —
exactly what soft targets like people produce.

## Decision
Each `SonarFrame` carries a spherical **intensity volume** `[R, A, E]` *and* a
thresholded **point cloud** `[N, 4]`. Clustering and display use points;
models may use either.

## Alternatives considered
- Points only — loses information, couples us to a threshold.
- Volume only — clustering and visualization become awkward.
- Raw per-mic waveforms — most information, but hardware-specific; revisit if
  real hardware lets us record them (could store optionally later).

## Consequences
- Bigger files (~216k floats/frame at defaults); fine for hackathon scale.
- Threshold choice only affects clustering, not information available to models.
