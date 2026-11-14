# 2026-11-14 (session 4) — Lying people

_Goal from the lead: "Tackle lying people." Decision record:
[ADR-0013](../decisions/0013-lying-people-sensing.md)._

## 1. Diagnosis (99 lying people, 500 scenes, v3-2000 RF)
- By range: <2.25 m: 52% undetectable (mean in-view fraction 0.43, so here it
  *is* field of view); 2.25-4 m: 37% undetectable, 35% → debris, 14% correct;
  >4 m: 58% undetectable.
- Of 47 undetectable: **13 outside the field of view, 34 in view but too weak**
  (fog 16, heavy 15, warm 8, clear 8).
- Lying person vs debris, feature medians: n points 4.89 vs 4.95 (log),
  horizontal extent 1.01 vs 1.05 m, vertical 0.61 vs 0.71 m, SNR 0.98 vs 0.97
  (log); only linearity differs (0.63 vs 0.42). **Indistinguishable from one view.**
- Hypotheses: ping averaging fixes weak echoes; multi-view sweep reveals more of
  the body and fixes the shape.

## 2. Built
- `SensorConfig.pings_averaged` (noise / √N).
- `SweepConfig` + `simulate_sweep`: N poses over a yaw span (optional forward
  step); each pose simulated with its own noise; points mapped back to the
  middle pose and voxel-fused at 5 cm. Later: `min_views`.
- CLI sensing flags on generate / detect / diagnose: `--pings`, `--sweep`,
  `--sweep-yaw`, `--sweep-step`, `--min-views`, `--tilt`. Rewrote
  `__main__.py` cleanly (it had grown inline imports).
- Single lying person at 3 m in fog, 8 orientations: visible 75% (single) →
  100% (4 pings / sweep); apparent length 1.10 → 1.29 (pings) → 1.40 m (sweep + pings).

## 3. Environment failure mid-experiment
- Halfway through the 5-variant run, every command failed with `No module
  named sonar_perception`. Cause: macOS set the **`hidden` flag** on
  `.venv/.../*.pth` (seen with `ls -lO`), and Python 3.12 skips hidden `.pth`
  files. Fixed with `chflags nohidden`; experiment scripts now set
  `PYTHONPATH=src`. Documented in AGENTS.md §6. Reran only the failed variants.

## 4. Results
See the table in ADR-0013. In short:
- **Pings ×4: the clear win.** Lying 20 → 32%, all people 55 → 58%.
- **Sweep as a union of views: worse.** Noise false alarms 5 → 38 per 200
  frames, because every pose's ghosts get added. Added a **2-of-3 view rule**
  (voxel ± 1 neighbor must be seen by ≥2 poses). Noise came back to 13, and
  lying reached 35% with precision 0.71. Only slightly better than pings alone.
- **Tilt 15° + sweep: worse overall (48.6%)**, even though lying visibility
  improved (undetectable 25%). Merges jumped to 24%: the floor enters the view
  and bridges objects. Needs ground removal first.

## 5. Where it stands
- Lying people **20% → 32-35%**; all people **55% → 58%** (1,000-scene models,
  bias 2). Recommended flags: `--pings 4 --bias person=2`.
- Hardware/firmware requirements added to `interfaces/sensor-geometry.md`:
  average 4 pings; IMU pose if sweep mode is used.
- Remaining lying-person failures: ~35% undetectable (physics), ~15% → debris.
