# ADR-0013: Lying people: average pings; sweep fusion only with a 2-of-3 view rule; no tilt without floor removal

- **Status:** accepted
- **Date:** 2026-11-14
- **Area:** perception + **hardware/firmware requirement**

## Context
After ADR-0012, people lying on the floor were detected correctly only 20% of
the time (with person bias). A diagnosis on 99 lying people in 500 scenes:

- **Undetectable (46%) is mostly weak echoes, not field of view.** Only 13 of
  47 were outside the field of view; 34 were in view but below the noise floor.
  A body lying flat presents curved, upward-facing surfaces that reflect sound
  away from a chest-height sensor, and fog or smoke weakens them further.
- **Visible lying people look like debris from one viewpoint.** Median size
  ~1.0 m, height ~0.6 m (beam blur), point count, and SNR were nearly identical;
  only elongation differed (0.63 vs 0.42).

## Options tested
1,000-scene random forest per option, end to end on 400 fresh scenes, person bias 2:

| Sensing | All people correct | Lying correct | Lying undetectable | Merged | Person precision | Noise false alarms /200 frames |
|---|---|---|---|---|---|---|
| Single ping (baseline) | 54.7% | 20% | 46% | 9.6% | 0.70 | 5 |
| **4 pings averaged** | **58.0%** | **32%** | 37% | 12% | 0.68 | 11 |
| 3-pose sweep (±20°), union | 52.9% | 19% | 43% | 10% | 0.70 | 38 |
| Sweep + 4 pings, union | 58.2% | 34% | 34% | 14% | 0.67 | 37 |
| **Sweep + 4 pings, 2-of-3 views** | **58.5%** | **35%** | 35% | 13% | **0.71** | 13 |
| Sweep + 4 pings + 15° tilt, union | 48.6% | 29% | 25% | **24%** | 0.65 | 55 |

## Decision
1. **Average 4 pings per frame** (`SensorConfig.pings_averaged`, `--pings 4`):
   the simplest, cheapest real gain, lifting lying people from 20% to 32%. It
   assumes the wearer is briefly still (~4× ping time; at 6 m range a ping
   round trip is ~35 ms, so ~0.15 s). **Firmware requirement.**
2. **Sweep fusion is optional "search mode"**, and only with the **2-of-3 view
   rule** (`--sweep 3 --sweep-yaw 40 --min-views 2`). A plain union of views
   adds every pose's noise and ghosts, giving 3-7× more false alarms. With the
   rule it matches or slightly beats pings alone (35% vs 32% lying, precision
   0.71 vs 0.68). The gap is within noise (~80 lying people per test), so it's
   not worth 3× scan time yet. Needs pose from an IMU (pose error not modeled).
3. **Don't tilt without floor removal.** Tilt makes more lying people visible
   (undetectable 46% → 25%), but floor points then bridge objects (merges
   10% → 24%), and the net result is worse. Revisit after implementing ground
   removal.
4. Code defaults stay at 1 ping / no sweep / no tilt, because those settings
   describe hardware behavior. The **recommended evaluation and demo flags**
   are `--pings 4 --bias person=2`.

## Consequences
- Lying people: **20% → 32-35%**. Still the weakest case, and 35% of them
  remain undetectable. What's left is physics: frequency, power, mounting
  height, or a handheld low scan.
- `SweepConfig` and `pings_averaged` model operating procedures the
  hardware/firmware team must actually support; this is recorded in
  `docs/interfaces/sensor-geometry.md`.
- Training and evaluation must use the same sensing flags (a fused or averaged
  cloud looks different from a single ping).
