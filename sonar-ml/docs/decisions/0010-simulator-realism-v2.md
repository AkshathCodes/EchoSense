# ADR-0010: Simulator realism v2: floor, doorways in walls, absolute noise, held-out conditions

- **Status:** accepted
- **Date:** 2026-11-14
- **Area:** perception

## Context
The v1 results (about 87% for every model) were optimistic: door frames stood
alone, there was no floor, and every test condition was also seen in training.
While adding realism, a deeper problem showed up: the simulated noise floor was
set **relative to each frame's brightest echo**, so a bright surface near the
sensor raised the noise and erased weaker objects. Real receiver noise doesn't
depend on the scene.

## Decision
1. **Floor plane** in every scene (`SimConfig.floor_prob = 1.0`). Floor returns
   are labeled `NOISE` (background), not a class.
2. **Doorways set into walls** with probability 0.6 (`doorway_in_wall_prob`):
   left and right wall segments plus a header above the lintel, as a separate
   `wall` instance touching the frame.
3. **Absolute noise floor**: `noise = SensorConfig.noise_reference · 10^(noise_level_db/20)`,
   with `noise_reference = 8e-5` (median frame peak, measured on 2026-11-14).
   The threshold relative to the brightest echo was relaxed from -30 to -50 dB
   (a dynamic-range limit), so the noise-aware term (ADR-0008) does the real work.
4. **Held-out `extreme` condition** (180 °C, 6 dB/m absorption, strong
   turbulence and multipath) that `EnvironmentConfig.random()` never samples.
   Used only for testing generalization.

## Findings that shaped it
- **The floor is barely visible** from chest height with a ±30° vertical field
  of view: 2-4% of points. Specular reflection sends most floor energy away
  from the sensor, and the floor only enters the field of view beyond ~2.2 m,
  at grazing angles. So ground removal was **not** implemented. Revisit with
  real data or a downward-tilted sensor.
- **Low objects within ~2 m of the sensor fall below the field of view** (for
  example, a person lying near the sensor's feet). This is a **hardware
  requirement**: tilt the sensor down, or widen the vertical field of view.
  Reported to hardware in `docs/interfaces/sensor-geometry.md`.
- About 18% of objects are not detectable at all (fewer than 8 points), mostly
  from occlusion and low signal-to-noise. Fixing the noise model did not raise
  visibility: it was 86% with relative noise and 82% with absolute noise. The
  absolute model is the physically correct one.

## Consequences
- v1 and v2 datasets are not comparable. `manifest.json` records the sim config;
  v1 predates these fields (equivalent to floor 0, doorway-in-wall 0,
  relative noise).
- `noise_reference` only means something for the simulator. Real hardware has
  its own noise floor, which CFAR estimates per frame.
