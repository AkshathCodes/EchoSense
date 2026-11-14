# Architecture

_Last updated 2026-11-14._

## Pipeline

```
 ┌──────────── hardware-specific ────────────┐   ┌──────────── hardware-agnostic ─────────────────────────┐
 chirp TX → mic array → matched filter → beamform → SonarFrame → segment → classify → app / cues
                                                    (volume +     (DBSCAN)  (encoder →
 simulator (sim/) ─────────────────────────────────→ points)                 embedding → head)
```

The **`SonarFrame`** is the seam. Anything left of it (real sensor driver or
simulator) can be swapped; anything right of it never knows which source it is
using. Spec: [interfaces/sonar-frame.md](interfaces/sonar-frame.md).
Rationale: [ADR-0001](decisions/0001-hardware-agnostic-interface.md).

## Stages and code

| Stage | What it does | Code |
|---|---|---|
| Source | Produce `SonarFrame`s | `sources/base.py` (`SensorSource`), `synthetic.py`, `recorded.py`, `live.py` (stub) |
| Simulation | Scene → labeled acoustic returns | `sim/shapes.py`, `sim/scene.py`, `sim/acoustics.py` |
| 3D mapping | Returns → spherical intensity volume (range × az × el) → thresholded point cloud | `grid.py` |
| Segmentation | Point cloud → object clusters | `segmentation.py` |
| Classification | Cluster → embedding → class | `features.py` + `baseline.py` (RF); `models/` (torch) |
| Datasets | Generate, save, split by scene | `dataset.py` |
| Viz | 3D scatter colored by class | `viz.py` |

## Key representation choices

- **Both** an intensity volume and a point cloud travel in each frame
  ([ADR-0002](decisions/0002-volume-plus-point-cloud.md)). Models may use either.
- Volume is gridded in the sensor's **native spherical coordinates**; blur is
  applied in angle, so physical blur grows with range
  ([ADR-0004](decisions/0004-spherical-native-coordinates.md)).
- Simulation models **specular reflection + occlusion**, not uniform surface
  sampling ([ADR-0003](decisions/0003-specular-simulation.md)).
- We **segment, then classify clusters**, rather than classifying whole frames
  ([ADR-0005](decisions/0005-segment-then-classify.md)).
- Model is picked by experiment across three baselines
  ([ADR-0007](decisions/0007-model-baselines.md)).
- Points are extracted with a relative **and** noise-aware (CFAR-style)
  threshold ([ADR-0008](decisions/0008-cfar-point-threshold.md)).

## Classes (v0)

Cluster classes: `0 wall`, `1 doorway`, `2 furniture`, `3 debris`,
`4 person` (= "person-sized object"), `5 noise` (a cluster of ghosts or
background, [ADR-0009](decisions/0009-noise-class.md)). Point labels use the same
ids 0-4 plus `-1` for noise/background points (ghosts, floor). Defined in
`sim/shapes.py::CLASSES`. Changing them is an interface change.

## Inference and outputs

```
SensorSource → SonarFrame → extract_clusters → classifier.predict_proba → Detection list → detections_*.json
```

`inference.py` loads either the random forest (`baseline_rf.joblib`) or a torch
run directory, and `detect` writes the format in
[interfaces/detections.md](interfaces/detections.md). On labeled frames it also
reports cluster accuracy, object recall (objects not dismissed as noise) and
noise rejection.

## Data flow for training

```
generate (sim) → scenes/*.npz (SonarFrame + per-point labels + instance ids)
              → clusters.npz (per-cluster points padded to N, features, label, scene_id)
              → baseline / train (split by scene_id)
```

## When hardware arrives

1. Hardware team fills in [interfaces/sensor-geometry.md](interfaces/sensor-geometry.md).
2. Update `SensorConfig` defaults to match (FOV, beam width, range resolution).
3. Implement `sources/live.py` to emit `SonarFrame`s.
4. Capture and hand-label a small real set → `data/recorded/…`.
5. Fine-tune; report synthetic vs real accuracy separately.
