# AGENTS.md — EchoSense monorepo

Map for AI agents and new teammates. Each area has its own docs; read the one
for the area you're changing before you change it.

| Path | What | Owner | Read first |
|---|---|---|---|
| repo root (`index.html`, `src/`, `serve.js`, `test/`) | Web scan viewer and saved maps (Node 20+, no packages) | viewer team | [README.md](README.md) |
| [`acoustic/`](acoustic/) | Audible-chirp laptop scanner, Databricks scan aggregation | Ryan | [README.md](README.md) "Acoustic Scan and Databricks" |
| [`lidar/`](lidar/) | **Current sensor (2026-11-14 pivot):** iPhone LiDAR capture app (Swift) + Mac live mapper (Python), dark-safe (no camera) | Rishi | [lidar/README.md](lidar/README.md), [ADR-0015](sonar-ml/docs/decisions/0015-iphone-lidar-dark-mapping.md) |
| [`sonar-ml/`](sonar-ml/) | Python sonar simulation, 3D mapping, segmentation, classification; research, decisions (ADRs), logs, hardware/firmware requirements | Rishi | [sonar-ml/AGENTS.md](sonar-ml/AGENTS.md), then [sonar-ml/docs/status.md](sonar-ml/docs/status.md) |

## Rules
- Stay in your area; changes to another area go through its owner.
- `main` should pass all suites: `node --test` (root),
  `cd sonar-ml/perception && pytest`, and `cd lidar/mapper && pytest`.
- How the areas relate (coordinate frames, formats, overlap):
  [sonar-ml/docs/status.md](sonar-ml/docs/status.md) "Relation to the rest of EchoSense".
