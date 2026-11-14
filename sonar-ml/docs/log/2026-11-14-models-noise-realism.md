# 2026-11-14 — Deep models, noise class, detections, realism v2

_Second work session (lead + Claude). Plan: (1) run the deep models, (2) noise
class, (3) detections format for the app team, (4) `detect` inference command,
(5) more realistic scenes plus a harder held-out test. Results tables are in
[status.md](../status.md)._

## 1. PyTorch install: wrong architecture

- `pip install torch` into a venv built on Anaconda's `python3` installed
  **torch 2.2.2**, which crashed against NumPy 2.5 ("Numpy is not available").
- Cause: Anaconda Python on the lead's **M4 Pro** is an **x86_64 build running
  under Rosetta**, and 2.2.2 is the last PyTorch built for Intel macOS.
- Fix: rebuilt `.venv` on the native arm64 Python at `/usr/local/bin/python3`,
  giving torch 2.15 with Apple GPU (MPS). Documented in AGENTS.md §6 and the
  READMEs.
- Lesson: on Apple silicon, check `platform.machine()` before trusting an
  environment.

## 2. Noise class (ADR-0009)

- Added cluster class `5 noise`. Point label `-1` is unchanged.
- With the noise-aware threshold, frames had almost no noise clusters, so the
  generator now draws detection thresholds per scene. First range (noise margin
  6-18 dB) made **64%** of clusters noise; narrowed to **10-18 dB**, about 20%
  on the v1 scene setup.

## 3. Detections format and `detect`

- `docs/interfaces/detections.md` v0.1: one JSON per frame with class,
  confidence, all class probabilities, centroid, range/azimuth/elevation in
  degrees, bounding box, and `gt_class` on synthetic frames. Noise is left out
  by default, and detections are sorted nearest first.
- `python -m sonar_perception detect --model <rf.joblib | torch run dir>
  --source <frames dir> | --synthetic N [--env …] --out <dir>`. On labeled
  data it reports cluster accuracy, object recall (objects not dismissed as
  noise) and noise rejection.

## 4. Deep models, and a bug in how I scored them

- First runs reported "best test acc" over epochs, i.e. **the epoch was chosen
  on the test set**, which inflates scores (BEV showed 0.881). Fixed: train,
  validation and test are all split by scene, the epoch is picked on
  validation, and test accuracy is reported only at that epoch.
- Added `compare` (RF + 3 models × 3 seeds, same test scenes per seed).
- **v1 result** (no floor, free-standing doors): RF 0.882 ± 0.017,
  BEV 0.870 ± 0.010, PointNet 0.867 ± 0.015, voxel 0.857 ± 0.012. **No deep
  model beat the random forest**; all are within about 1 std. Training takes
  11-54 s per model on the M4 Pro GPU.

## 5. Realism v2, and a noise-model flaw found along the way (ADR-0010)

- Added a floor plane and doorways set into walls (60%).
- Debugging one frame where a single cluster swallowed everything showed that a
  bright surface near the sensor erased weaker objects. Lowering the relative
  threshold changed nothing, because the **simulated noise floor itself was
  relative to the frame's brightest echo**. Made it absolute
  (`noise_reference`). Object visibility stayed about the same (86% → 82%),
  because the remaining misses are occlusion and low signal-to-noise. The
  absolute model is the physically correct one.
- **Floor:** only 2-4% of points at chest height with ±30° elevation.
  Specular reflection sends floor energy away from the sensor. No ground
  removal implemented.
- **Field-of-view finding for hardware:** floor-level objects within ~2.2 m are
  below the vertical field of view. Recommend tilting the sensor down 10-20° or
  widening elevation. Added to `interfaces/sensor-geometry.md`.
- **Held-out `extreme` condition** (180 °C, 6 dB/m) is never used in training.
- v2 dataset (600 scenes): 3,362 clusters, **41% noise**, doorway clusters
  down from 283 to 160 (merged into walls), purity 0.96 → 0.90.

## 6. Results on v2

3 seeds, split by scene; same test scenes per seed for all models.

| Model | Test acc | clear | fog | warm | heavy | person recall | noise recall |
|---|---|---|---|---|---|---|---|
| Random forest | **0.870 ± 0.013** | 0.870 | 0.865 | 0.896 | 0.852 | **0.67** | 0.94 |
| Voxel CNN | 0.853 ± 0.015 | 0.816 | 0.881 | 0.876 | 0.843 | 0.57 | 0.95 |
| BEV CNN | 0.845 ± 0.018 | 0.808 | 0.855 | 0.860 | 0.857 | 0.56 | 0.96 |
| PointNet | 0.824 ± 0.017 | 0.816 | 0.842 | 0.841 | 0.800 | 0.62 | 0.91 |

- The random forest still wins. Person recall dropped from about 0.72-0.74
  (v1) to 0.56-0.67 (v2), and varies a lot by seed (one BEV seed: 0.41),
  because there are only about 60 person clusters per test split.
- Overall accuracy is propped up by the noise class (41% of clusters, easy to
  reject). **Report per-class recall, not just accuracy.**

**Held-out `extreme` condition** (150 fresh scenes, seed 777, models trained on v2 seed 0):

| | Fresh scenes, training-like conditions (RF) | Extreme (RF) | Extreme (BEV) |
|---|---|---|---|
| Detections kept (non-noise) | 482 | **82** | 80 |
| Cluster accuracy | 0.84 | **0.58** | 0.56 |
| Object recall (not dismissed as noise) | 0.98 | 0.92 | 0.89 |
| Noise rejection | 0.85 | 0.86 | 0.71 |

- In extreme conditions the **sensing fails before the classifier does**: 6× fewer
  objects produce a cluster at all (6 dB/m absorption pushes most echoes under
  the noise floor), and the ones that do are classified at 58%. Generalization
  past the training conditions is weak. Either train with wider condition
  ranges, or accept that the sensor's range shrinks sharply in extreme heat
  and smoke, and say so in the pitch.

## 7. Takeaways and next steps

1. **No deep model is justified yet** → [ADR-0011](../decisions/0011-model-choice-v2.md): random forest is the default classifier for the demo.
2. **Biggest lever now is data size and segmentation, not model architecture**: 1,500-2,000 scenes for stable person numbers; splitting doorways from walls.
3. **Extreme-condition range loss** is a physics or hardware story (power, frequency, chirp length), not an ML one. Raise it with the hardware team: a lower frequency attenuates less, at the cost of resolution.
