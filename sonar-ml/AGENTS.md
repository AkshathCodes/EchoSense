# AGENTS.md — onboarding for AI agents and new teammates

Read this whole file before changing anything. It is the canonical entry point;
`CLAUDE.md` just points here.

## 0. Where you are

This is `sonar-ml/` inside the **EchoSense** monorepo (ported from the
standalone `madhacks-sonar` repo on 2026-11-14; history before that lives in
`Rishi-S20/madhacks-sonar`). Other parts of the monorepo:

| Path | What | Relation to sonar-ml |
|---|---|---|
| repo root (`index.html`, `src/`, `serve.js`, `test/`) | Web scan viewer (Node, WebGL) | The demo UI. Its feed expects flat XYZ points + an optional target; no agreed wire format yet (see root README "Backend handoff") |
| `acoustic/` | Audible-chirp scanner (laptop speaker + mic, 1-4 kHz), Databricks aggregation | Overlaps our signal-processing step; see [docs/status.md](docs/status.md) "Relation to acoustic/" |

**Run every command in this file from `sonar-ml/`.** The venv is
`sonar-ml/.venv`; data goes in `sonar-ml/data/` (git-ignored).

## 1. What this project is (30 seconds)

Firefighters lose visibility in smoke. Thermal cameras help but have blind
spots (glass, reflective surfaces, fogged lenses, no "seeing through" things).
We are building a **sonar → 3D map → segment → classify** pipeline that works
without light. Full context: [docs/project-overview.md](docs/project-overview.md).

## 2. Where things stand

Always check [docs/status.md](docs/status.md) first — it says what works, what
is stubbed, and what is next. Update it when you finish something.

## 3. How knowledge is organized

| Need | Go to |
|---|---|
| Why we chose X over Y | [docs/decisions/](docs/decisions/) (ADRs, numbered) |
| What we tried, what failed, what we corrected | [docs/log/](docs/log/) (dated entries) |
| Prior art and sources | [docs/research/](docs/research/) |
| Hardware ↔ software contract | [docs/interfaces/](docs/interfaces/) |
| Unresolved questions | [docs/open-questions.md](docs/open-questions.md) |

## 4. Rules for working in this repo

1. **Respect the interface.** Everything downstream of the sensor consumes a
   `SonarFrame` ([spec](docs/interfaces/sonar-frame.md)). Do not make
   perception code depend on a specific sensor. If the contract must change,
   bump its version, update the spec, and write an ADR.
2. **Write down decisions.** A choice someone might later question (model,
   representation, physics assumption, scope cut) gets an ADR in
   `docs/decisions/` using [the template](docs/decisions/0000-template.md).
3. **Log trial and error.** At the end of a work session, add or extend a dated
   entry in `docs/log/` — include what *didn't* work and any correction to
   earlier claims. Mistakes are valuable; do not delete them, mark them
   superseded.
4. **Don't overclaim.** We say "person-sized object" unless validated on real
   humans. We do not claim fire-behavior prediction (see
   [ADR-0006](docs/decisions/0006-defer-fire-prediction.md)). Mark anything
   unverified as unverified.
5. **Stay in your folder.** Sub-teams own folders (see README). Don't edit the
   viewer or `acoustic/` from here without their owners.
   Cross-folder changes go through the interface docs.
6. **Simulated ≠ real.** Any accuracy number must say which data it came from
   (synthetic version, real capture set, conditions).
7. **Measure end to end.** Per-cluster recall overstates performance: it ignores
   objects that were never detected or got merged. For people, quote the
   `diagnose` end-to-end rate, and false detections per frame for noise.

## 5. Perception package map

`perception/src/sonar_perception/`

| Module | Role |
|---|---|
| `frame.py` | `SonarFrame`, `SphericalGrid` — the contract in code; save/load |
| `config.py` | Sensor / environment / sim config dataclasses |
| `sources/` | `SensorSource` interface; `synthetic`, `recorded`, `live` (stub) |
| `sim/shapes.py` | Primitive objects (wall, doorway, box, person) as labeled surface samples |
| `sim/scene.py` | Random scene composer |
| `sim/acoustics.py` | Specular reflection, occlusion, attenuation, temperature, multipath, beam blur |
| `grid.py` | Spherical ↔ Cartesian, rasterize to intensity volume, extract points |
| `segmentation.py` | DBSCAN clustering into object candidates |
| `features.py` | Hand-crafted cluster features (non-deep baseline) |
| `views.py` | Fixed-size model inputs per cluster: point set, BEV images, voxels |
| `dataset.py` | Generate/save/load synthetic datasets, split by scene |
| `baseline.py` | Random-forest classifier on cluster features (runs without torch) |
| `models/` | PyTorch encoders (PointNet, voxel 3D CNN, BEV 2D CNN) + head |
| `train.py` | Torch training: train/val/test split by scene, epoch picked on val |
| `compare.py` | RF + deep models over several seeds → `compare.json` |
| `detections.py` | `Detection` + JSON format (docs/interfaces/detections.md) |
| `inference.py` | Load RF or torch classifier (optionally cost-biased, e.g. `person=2`); `run_detect` over any source |
| `diagnostics.py` | Follow every ground-truth object of a class end to end: invisible / merged / misclassified / correct, by pose and range |
| `viz.py` | Matplotlib 3D viewer |
| `__main__.py` | CLI: `generate`, `baseline`, `train`, `compare`, `detect`, `diagnose`, `view` |

## 6. Environment and commands

**Use the repo venv** (`.venv/`, git-ignored). It's built on the native arm64
Python at `/usr/local/bin/python3`. The Anaconda `python3` on the lead's Mac is
an **x86_64 build under Rosetta**, so pip installs an old Intel-only PyTorch
(2.2.2) that breaks with NumPy 2. See log 2026-11-14 §1.

**If `No module named sonar_perception` appears suddenly** (it happened mid-run on
2026-11-14): macOS put the `hidden` flag on `.venv/.../*.pth` (`ls -lO` shows it),
and Python 3.12 skips hidden `.pth` files. Fix with
`chflags nohidden .venv/lib/python3.12/site-packages/*.pth`, or sidestep it by
running from `perception/` with `PYTHONPATH=src`. Long scripts should set
`PYTHONPATH=src`.

```bash
/usr/local/bin/python3 -m venv .venv && .venv/bin/pip install -e "perception[dev,torch]"
cd perception && ../.venv/bin/python -m pytest
P=../.venv/bin/python
$P -m sonar_perception generate --scenes 600 --out ../data/synthetic/v2
$P -m sonar_perception baseline --data ../data/synthetic/v2          # also saves baseline_rf.joblib
$P -m sonar_perception compare  --data ../data/synthetic/v2 --seeds 0 1 2 --out ../runs
$P -m sonar_perception detect   --model ../data/synthetic/v2/baseline_rf.joblib --synthetic 50 --env extreme --out ../data/detections/demo
$P -m sonar_perception diagnose --model ../data/synthetic/v2/baseline_rf.joblib --class person --scenes 400 [--bias person=2] [--tilt 15]
$P -m sonar_perception view     --data ../data/synthetic/v2 --scene 0
```
