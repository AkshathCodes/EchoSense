# Interface: sensor geometry (TO BE FILLED by hardware)

_Status 2026-11-14: unknown — no hardware yet. Perception uses the placeholder
defaults in `perception/src/sonar_perception/config.py::SensorConfig`._

| Parameter | Placeholder (sim default) | Real value | Notes |
|---|---|---|---|
| TX center frequency | 40 kHz | | |
| Chirp band | 35–45 kHz | | Wider band → better range resolution |
| Max range | 6.0 m | | |
| Range bin | 0.05 m | | Set by bandwidth: Δr ≈ c / (2B) ≈ 1.7 cm at 10 kHz |
| Azimuth FOV | ±60° | | |
| Elevation FOV | ±30° | | |
| Angular bin | 2° | | |
| Beam / angular resolution (σ) | 4° | | Drives angular blur in sim; depends on array aperture |
| Mic count + positions | n/a | | mm, sensor frame (x fwd, y left, z up) |
| Sample rate | n/a | | ≥ 192 kHz expected |
| Frame rate | n/a | | |
| Scan method | n/a | | pan-tilt vs. static array |
| Temperature sensor | assumed | | needed for speed-of-sound correction |

## Requirements learned from simulation (2026-11-14)

- **Vertical field of view and mounting.** With the sensor at chest height
  (~1.3 m) and ±30° elevation, anything on the floor closer than ~2.2 m is out
  of view. A person lying near the user's feet would be missed. Widening
  elevation is preferred; tilting needs floor removal first (see ADR-0013).
  [ADR-0010](../decisions/0010-simulator-realism-v2.md).
- **Temperature sensor.** Warm air shortens measured ranges (about 11% at
  100 °C). Include a thermistor.
- **Average 4 pings per frame** (firmware). This lifted lying-person detection
  from 20% to 32% in simulation ([ADR-0013](../decisions/0013-lying-people-sensing.md)).
  It costs ~4 ping round trips (~0.15 s at 6 m) and assumes the wearer is
  briefly still.
- **IMU (optional, for sweep mode).** Fusing 3 views over a ±20° side-to-side
  sweep needs each view's orientation. The simulator assumes perfect pose.
- **Don't tilt the sensor down unless perception gets floor removal**: tilt
  brings the floor into view and doubled object merging in simulation.

When filled, update `SensorConfig` defaults and regenerate synthetic data with a
new dataset version.
