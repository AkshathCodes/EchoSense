# ADR-0004: Grid and blur in spherical (range, azimuth, elevation) coordinates

- **Status:** accepted
- **Date:** 2026-11-14
- **Area:** perception

## Context
A sonar array measures time-of-flight (range) and direction (angles). Its
angular resolution is roughly fixed in degrees, so the physical blur in meters
grows with distance. Blurring in Cartesian x/y/z would make distant objects
look as sharp as near ones.

## Decision
The `SonarFrame` volume is binned in range × azimuth × elevation. Simulated
beam blur is a Gaussian in angle (σ from `SensorConfig.beam_sigma_deg`) and in
range (`range_sigma_m`). Points are converted to Cartesian only after
thresholding, for clustering and display.

## Consequences
- Matches how a real beamformer produces data; drop-in for real sensors.
- Models on the volume see a non-uniform Cartesian sampling — fine for CNNs; a
  Cartesian voxel/BEV projection is still available via `grid.py` helpers.
