# sonar-ml: sonar perception for EchoSense

> This folder is the sonar simulation and ML part of the **EchoSense** monorepo
> (it was ported from the standalone `madhacks-sonar` repo on 2026-11-14). The
> web scan viewer lives at the repo root and Ryan's audible-chirp scanner in
> [`../acoustic/`](../acoustic/). **Run every command below from `sonar-ml/`.**

A MadHacks project: **sonar-based perception for firefighters in low-visibility
environments** (dense smoke, darkness) where cameras and camera-based object
detection fail.

An ultrasonic sonar sensor builds a coarse 3D map of the space ahead. Software
segments that map into objects and classifies each one (wall, doorway,
furniture, debris, person-sized object), and shows the result to the user.

> Status (2026-11-14): **no hardware yet.** Perception runs end to end on
> *simulated* sonar data: simulation → 3D map → clusters → classifier → detections JSON. See
> [docs/status.md](docs/status.md).

## Layout

Each folder is owned by a sub-team and talks to the others only through the
contracts in [`docs/interfaces/`](docs/interfaces/).

| Folder | What lives here | Owner |
|---|---|---|
| [`docs/`](docs/) | Project knowledge: research, decisions, logs, interfaces | everyone |
| [`perception/`](perception/) | Python: simulation, data pipeline, 3D mapping, segmentation, classification | software / ML |
| [`hardware/`](hardware/) | Sensor design, BOM, wiring, CAD | hardware |
| [`firmware/`](firmware/) | Microcontroller code: chirp TX, mic capture, streaming | hardware / embedded |
| [`../`](../) (repo root: `index.html`, `src/`) | EchoSense web scan viewer: the demo UI | frontend |
| [`../acoustic/`](../acoustic/) | Audible-chirp laptop scanner + Databricks aggregation | Ryan |
| [`databricks/`](databricks/README.md) + `databricks.yml` | Databricks Asset Bundle: lakehouse tables, pipeline, MLflow, jobs | software / ML |
| [`data/`](data/) | Local datasets (git-ignored contents) | everyone |

## Start here

- **New teammate or AI agent:** read [`AGENTS.md`](AGENTS.md) first.
- **What and why:** [docs/project-overview.md](docs/project-overview.md)
- **How the system fits together:** [docs/architecture.md](docs/architecture.md)
- **The hardware ↔ software contract:** [docs/interfaces/sonar-frame.md](docs/interfaces/sonar-frame.md)
- **How we got here (incl. mistakes):** [docs/log/](docs/log/)

## Quick start (perception)

```bash
/usr/local/bin/python3 -m venv .venv            # native arm64 Python; see AGENTS.md §6
.venv/bin/pip install -e "perception[dev,torch]"
cd perception && ../.venv/bin/python -m pytest
../.venv/bin/python -m sonar_perception generate --scenes 600 --out ../data/synthetic/v2
../.venv/bin/python -m sonar_perception compare --data ../data/synthetic/v2 --out ../runs
```

More commands: [perception/README.md](perception/README.md).
