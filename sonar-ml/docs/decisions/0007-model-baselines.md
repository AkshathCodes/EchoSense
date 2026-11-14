# ADR-0007: Choose the model by experiment across baselines

- **Status:** accepted
- **Date:** 2026-11-14
- **Area:** perception

## Context
The first plan picked PointNet. Radar point-cloud literature (also sparse,
noisy) shows plain point-set models can struggle, while 2D pillar/BEV
projections did well. We don't know our real data's density yet.

## Decision
Run on the same synthetic clusters, same split:
0. **Random forest on hand-crafted cluster features** (`baseline.py`) — runs without torch, sanity floor.
1. **BEV / front-projection 2D CNN** (`models/encoders.py::BEVEncoder`).
2. **PointNet** on resampled points (`PointNetEncoder`).
3. **Voxel 3D CNN** on a small occupancy+intensity grid (`VoxelEncoder`).

All deep models share an `encoder → embedding (128-d) → head` split so
embeddings are usable for nearest-neighbor / open-set checks.

## Consequences
- Pick the winner by accuracy across degradation levels, not clean-data accuracy.
- Re-run when real data arrives; the winner may change.
