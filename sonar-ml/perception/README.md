# perception/

Python package `sonar_perception`: physics-informed sonar simulation, 3D
mapping, segmentation, and classification. Hardware-agnostic: everything
consumes a `SonarFrame` ([spec](../docs/interfaces/sonar-frame.md)).

## Install

Use a **native** Python 3.10+ (on Apple silicon, check `python3 -c "import platform; print(platform.machine())"` says `arm64`, otherwise pip installs an old Intel PyTorch). From `sonar-ml/`:

```bash
/usr/local/bin/python3 -m venv .venv
.venv/bin/pip install -e "perception[dev,torch]"
cd perception && ../.venv/bin/python -m pytest
```

If imports suddenly fail with `No module named sonar_perception`, macOS has
flagged the venv's `.pth` files hidden. Run
`chflags nohidden ../.venv/lib/python3.12/site-packages/*.pth` or prefix
commands with `PYTHONPATH=src` (see AGENTS.md §6).

## Use (from `perception/`, with `P=../.venv/bin/python`)

```bash
# 1. simulate scenes -> SonarFrames + cluster dataset (~1-2 min for 600 scenes)
$P -m sonar_perception generate --scenes 600 --out ../data/synthetic/v2
#    --env clear|fog|warm|heavy|extreme to fix conditions (default: random per scene; extreme is never used in random)

# 2. random-forest baseline (saves baseline_rf.joblib)
$P -m sonar_perception baseline --data ../data/synthetic/v2

# 3. deep models
$P -m sonar_perception train --data ../data/synthetic/v2 --model bev --out ../runs     # or pointnet, voxel
$P -m sonar_perception compare --data ../data/synthetic/v2 --seeds 0 1 2 --out ../runs  # all models x seeds

# 4. inference -> detections JSON (docs/interfaces/detections.md)
$P -m sonar_perception detect --model ../data/synthetic/v2/baseline_rf.joblib --source ../data/synthetic/v2/scenes --out ../data/detections/v2
$P -m sonar_perception detect --model ../runs/bev-s0-<timestamp> --synthetic 100 --env extreme

# 5. where are people (or any class) being lost? end-to-end, by pose / range / conditions
$P -m sonar_perception diagnose --model ../data/synthetic/v2/baseline_rf.joblib --class person --scenes 400
#    --bias person=2   cost-sensitive decision (more recall, less precision)
#    --tilt 15         sensor pitched down 15 deg (also on generate / detect)

# 6. look at a scene
$P -m sonar_perception view --data ../data/synthetic/v2 --scene 2 --color label   # or cluster, intensity
```

## Pipeline

```
Scene (sim/scene.py)
  → acoustic returns (sim/acoustics.py: specular, occlusion, absorption, temperature, ghosts)
  → spherical volume (grid.rasterize) → blur + TVG + noise (grid.apply_sensor_response)
  → points (grid.extract_points: relative + CFAR-style threshold, labels carried)
  = SonarFrame
  → DBSCAN clusters (segmentation.py)
  → features (features.py) → random forest (baseline.py)
  → views (views.py) → torch encoders → 128-d embedding → head (models/, train.py)
  → Detection JSON (detections.py, inference.py)
```

## Python API

```python
from sonar_perception.sources import SyntheticSource, RecordedSource
from sonar_perception.segmentation import extract_clusters

for frame in SyntheticSource(n_frames=10, seed=0):     # or RecordedSource("../data/recorded/…")
    clusters, ids = extract_clusters(frame)
```

## Where to change things

| Want to… | Edit |
|---|---|
| Match real hardware (FOV, resolution, beam) | `config.py::SensorConfig` (+ docs/interfaces/sensor-geometry.md) |
| Change air/smoke/heat assumptions | `config.py::ENV_PRESETS` |
| Change the reflection model | `sim/acoustics.py`, `config.py::SimConfig` |
| Add an object type | `sim/shapes.py` (builder + `CLASSES` + `REFLECTIVITY`) and `sim/scene.py::build_object` — **class changes are an interface change** |
| Plug in a real sensor | `sources/live.py` |
| Add a model | `models/encoders.py::make_encoder`, `views.py`, `train.py::build_inputs` |

Results and what's verified: [docs/status.md](../docs/status.md).
