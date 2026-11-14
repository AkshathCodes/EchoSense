# ADR-0005: Segment the scene, then classify each cluster

- **Status:** accepted
- **Date:** 2026-11-14
- **Area:** perception

## Context
The first plan classified a whole frame. Real scans contain several objects
at once (wall + doorway + chair + person), so a single label per frame is wrong.

## Decision
Pipeline: `SonarFrame` → **DBSCAN** on points (xyz) → per-cluster classifier.
Clusters are normalized (centered), and resampled/padded to a fixed point count
for neural models. Training labels per cluster = majority ground-truth class of
its points; clusters dominated by noise are labeled `-1` and excluded (or kept
as a "noise" class — open).

## Alternatives considered
- Whole-frame classification — wrong task.
- 3D U-Net semantic segmentation on the volume (as in Liu et al. 2026) — better
  in principle; **stretch goal** once the cluster pipeline works.

## Consequences
- Segmentation errors (merged or split objects) cap classifier accuracy; report
  segmentation quality (purity) alongside classification accuracy.
- DBSCAN `eps` depends on range resolution and beam blur → config.
