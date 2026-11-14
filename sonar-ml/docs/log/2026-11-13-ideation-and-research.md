# 2026-11-13 → 2026-11-14 — Ideation, research, and the first scaffold

_Planning conversation between the project lead and an AI assistant (Claude),
then repo scaffold. Written so a new agent or teammate can follow the reasoning,
including wrong turns. Newest corrections are marked **CORRECTION**._

## 1. Starting idea

> Sonar to detect objects in low-visibility areas (fires) where cameras and
> object detection fail, for firefighters.

## 2. First research pass — what exists for firefighters

Details: [research/01-firefighter-landscape.md](../research/01-firefighter-landscape.md).

- Thermal cameras are standard; known blind spots (reflective surfaces, fogged lenses, can't see through obstructions, over-reliance).
- Qwake C-THRU AR helmet = closest product; DHS testing; weight/fit complaints.
- NIST work is about *tracking firefighters*, not perceiving surroundings.
- Radar performs best in smoke; LIDAR fails below ~4 m visibility.
- **Ultrasound is distorted by flames and hot smoke** (UT Austin: off-the-shelf rangefinders failed through flame → pulse-compression sonar worked better).
- No deployed wearable sonar found → the gap we target.

Search misses: a query for "Haptic Navigation Belt" / DHS Responder Technology returned nothing; haptic devices remain unresearched.

## 3. Idea expanded, then trimmed

Lead's expanded idea: sonar → **classification model** for targets → plus a
**prediction model** for (a) fire about to intensify and (b) where people
could be.

Assessment:
- Classification: feasible.
- (a) Fire prediction: **cut** — sonar can't measure combustion. Salvaged the
  speed-of-sound/temperature idea as a stretch indicator.
- (b) People prediction: reframed as a search-priority heuristic, labeled as guidance.
→ [ADR-0006](../decisions/0006-defer-fire-prediction.md)

## 4. First technical plan (partly superseded)

Proposed: chirp TX → mic array → matched filter → beamform → **point cloud** →
**PointNet** embedding → classifier; pre-train on **ModelNet/ShapeNet meshes
uniformly sampled + noise**, fine-tune on real captures; 4–6 classes;
split by session not frame; report clear vs fog vs warm.

Hardware options floated: pan-tilt servo scan (easy, slow, blurry) vs.
ultrasonic MEMS mic array with beamforming (credible, harder). Audio-band arrays
(ReSpeaker) won't work. Teensy/STM32 over ESP32.

Note: an earlier answer started recommending a single HC-SR04 and was
interrupted; the HC-SR04 only gives one range number and can't support 3D
mapping. Don't use it except as a quick sanity test.

## 5. Lead's direction: software first, hardware TBD

The lead wanted the sonar to output a **3D map**, build **embeddings** from
it, and train the classifier — and asked whether unknown hardware changes the
software. Answer: signal processing depends heavily on hardware, the 3D map
moderately, the classifier barely, *if* the interface is fixed.
→ [ADR-0001](../decisions/0001-hardware-agnostic-interface.md)

## 6. Second research pass — in-air sonar ML (changed the plan)

Details: [research/02-in-air-sonar-and-ml.md](../research/02-in-air-sonar-and-ml.md).
Findings and resulting changes:

| Earlier plan | What we learned | Change |
|---|---|---|
| Point cloud is the only data | Published sonar ML used dense echo images / volumes | Volume + points → [ADR-0002](../decisions/0002-volume-plus-point-cloud.md) |
| Uniform mesh sampling + noise | Ultrasound is specular: oblique walls vanish, edges bright, soft targets weak | Specular + occlusion sim → [ADR-0003](../decisions/0003-specular-simulation.md) |
| Blur in x/y/z | Sonar resolution is angular; blur grows with range | Spherical grid → [ADR-0004](../decisions/0004-spherical-native-coordinates.md) |
| Classify the whole frame | Scenes contain many objects | DBSCAN → classify clusters → [ADR-0005](../decisions/0005-segment-then-classify.md) |
| PointNet | Plain point models struggle on sparse radar clouds; 2D projections do well | 3+1 baselines → [ADR-0007](../decisions/0007-model-baselines.md) |

Also learned: Calyo Pulse eval kit outputs point clouds via a Python SDK — a
possible hardware shortcut. Antwerp's 97% reflector classifier used only real
data (no sim) → expect a sim-to-real gap.

## 7. **CORRECTION** — warm air makes objects read *closer*, not farther

The second research summary said: "warm air speeds up sound, so objects read
farther than they are." **That is backwards.** Measured range is
`r_meas = c_assumed · t / 2` with `t = 2 r / c_true`, so
`r_meas = r · c_assumed / c_true`. Warm air → `c_true` larger → echo returns
sooner → **object appears closer**. At 100 °C, `c ≈ 387 m/s` vs 343 assumed →
ranges read ~11% short. Implemented correctly in `sim/acoustics.py`
(`range_scale`). Found while writing the simulator on 2026-11-14.

## 8. Scaffold built (2026-11-14)

Monorepo with `perception/`, `hardware/`, `firmware/`, `app/`, `docs/`, `data/`.
Perception package implements the full sim → volume → points → DBSCAN →
features → random-forest pipeline in numpy/scipy/scikit-learn; PyTorch models
and training loop written but **not executed** (torch not installed on the
lead's machine at time of writing). See [status.md](../status.md) for what
was actually run and the numbers.

Repo-structure decision: one monorepo, top-level folder per sub-team
(`perception/`, `hardware/`, `firmware/`, `app/`), shared `docs/` with
interfaces as the only cross-team coupling, ADRs for decisions, dated logs for
trial and error, `AGENTS.md` as the single onboarding file for AI agents
(`CLAUDE.md` points to it). Rationale: a hackathon team needs one clone, one
place for context, and clear ownership boundaries.

## 9. Lessons from building and testing the simulator (2026-11-14)

1. **Wrong test, right physics — large walls stay bright when rotated.**
   A test expected a wall rotated 70° to return 5× less than a facing wall;
   it was only ~2.7× less. Cause: a large wall keeps a **specular point**
   wherever the perpendicular from the sensor lands on it, so rotation alone
   doesn't hide it. What *does* fade: small surfaces turned away (a 0.6 m
   panel at 60° → ~12× dimmer) and walls parallel to the line of sight
   (side wall ~4.7× dimmer than back wall). Tests rewritten to check those.
   Implication: "oblique walls vanish" (§6) is only true for surfaces too
   small to contain their specular point.
2. **Noise flooded the point cloud in heavy conditions.** With a fixed
   threshold of -30 dB relative to peak and a -35 dB noise floor, ~7% of all
   voxels passed → 23k points per frame, 6,131 junk clusters across 400
   scenes. Fix: crude global **CFAR** — threshold also ≥ noise median + 15 dB
   (`SensorConfig.noise_margin_db`). After: ~5k points per frame, 3 noise
   clusters, purity 0.94 → 0.96, baseline accuracy 0.863 → 0.871 (heavy
   0.75 → 0.83). Real sonars use CFAR detectors; implement a proper local
   CFAR when real data arrives.
3. **Timing:** a bare frame simulates in ~0.03 s; with clustering, label
   transfer, and saving, `generate` takes ~55 s for 400 scenes on the
   lead's Mac.
4. **First baseline:** random forest on hand-crafted features: 87.1%
   (synthetic, split by scene). Person is the weakest class (recall 0.72,
   confused with furniture). Height features dominate. Numbers and caveats
   in [status.md](../status.md).

## Open threads carried forward
See [open-questions.md](../open-questions.md).
