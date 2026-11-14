# ADR-0011: Random forest is the default classifier, for now

- **Status:** accepted (revisit with ≥1,500 scenes or any real data)
- **Date:** 2026-11-14
- **Area:** perception
- **Resolves (for now):** [ADR-0007](0007-model-baselines.md)

## Context
ADR-0007 said to pick the model by experiment. `compare` ran the random forest
plus three deep models × 3 seeds on v1 (600 scenes, easy) and v2 (600 scenes,
floor, doorways in walls, absolute noise).

| Dataset | RF | BEV | PointNet | Voxel |
|---|---|---|---|---|
| v1 test acc | **0.882 ± 0.017** | 0.870 ± 0.010 | 0.867 ± 0.015 | 0.857 ± 0.012 |
| v2 test acc | **0.870 ± 0.013** | 0.845 ± 0.018 | 0.824 ± 0.017 | 0.853 ± 0.015 |
| v2 person recall | **0.67** | 0.56 | 0.62 | 0.57 |

## Decision
Use the **random forest on hand-crafted features** as the default classifier
for `detect` and the demo. Keep the deep models and `compare` in the codebase.

## Why
- It's best or tied on every metric, it trains in seconds, it needs no GPU, and
  feature importances explain its decisions (height and shape dominate).
- With about 2-3k clusters, the deep models have too little data to beat
  features, and their seed-to-seed spread (person recall 0.41-0.67 for BEV) is
  larger than the gaps between models.

## Revisit when
- The dataset grows to ≥1,500 scenes (`generate --scenes 2000`, ~5 min), or
- multi-frame stacking or richer echo features (time-frequency, like Antwerp's
  cochleograms) give the deep models something features can't capture, or
- real captures arrive (re-run `compare` on real data before trusting any model).

Note: the deep models' **128-d embeddings** are still useful for open-set
checks ("this cluster looks unlike anything seen in training") even if they
don't classify best.
