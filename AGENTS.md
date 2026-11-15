# AGENTS.md — EchoSense monorepo

Map for AI agents and new teammates. Each area has its own docs; read the one
for the area you're changing before you change it.

| Path | What | Owner | Read first |
|---|---|---|---|
| [`ios-lidar/`](ios-lidar/) | Fallback only: ARKit LiDAR publisher for the `lidar_frame` v1 bridge (Swift, never compiled). The demo uses `lidar/` | Ryan | [ios-lidar/README.md](ios-lidar/README.md) |
| [`websocket-bridge/`](websocket-bridge/) | Python bridge: LiDAR publish/view, record, replay; sonar replay | Charvik | [LIDAR_PROTOCOL.md](websocket-bridge/LIDAR_PROTOCOL.md) |
| repo root (`index.html`, `src/`, `serve.js`, `test/`) | Web viewer, LiDAR rendering (`src/lidar.js`), saved maps (Node 20+, no packages) | Akshath | [README.md](README.md) |
| `src/spatial-memory.js`, `src/room-classifier.js`, `src/room-plan.js`, `src/audio-cues.js`, [`docs/DEMO.md`](docs/DEMO.md) | Voxel memory, coverage map, room classification and floor plan, audio cues, demo plan | Ryan | [README.md](README.md) "LiDAR spatial memory" |
| [`hardware/hcsr04/`](hardware/hcsr04/) | HC-SR04 sonar firmware, wiring and mounting; cross-check logic lives in `lidar/mapper/src/lidar_mapper/sonar.py` | Ryan | [hardware/hcsr04/README.md](hardware/hcsr04/README.md) |
| [`acoustic/`](acoustic/) | Audible-chirp laptop scanner, Databricks scan aggregation | Ryan | [README.md](README.md) "Acoustic Scan and Databricks" |
| [`lidar/`](lidar/) | **Demo sensor path:** iPhone LiDAR capture app (Swift) + Mac live mapper (Python), dark-safe (no camera), run on a real phone | Rishi | [lidar/README.md](lidar/README.md), [ADR-0015](sonar-ml/docs/decisions/0015-iphone-lidar-dark-mapping.md) |
| [`sonar-ml/`](sonar-ml/) | Python sonar simulation, 3D mapping, segmentation, classification; research, decisions (ADRs), logs, hardware/firmware requirements | Rishi | [sonar-ml/AGENTS.md](sonar-ml/AGENTS.md), then [sonar-ml/docs/status.md](sonar-ml/docs/status.md) |

## Rules
- Stay in your area; changes to another area go through its owner.
- No unilateral pushes or merges to `main`. Branch from `develop` as `<area>/<short-name>`
  (`ios/`, `bridge/`, `viewer/`, `memory/`), open a pull request into `develop`, and tell the
  team before `develop` goes to `main`.
- The LiDAR schema and coordinate rules change in `LIDAR_PROTOCOL.md` first, announced to the team.
- Synthetic data stays labeled synthetic. Only real phone measurements are called real LiDAR.
- `main` should pass all suites: `node --test` (root), `cd websocket-bridge && pytest`,
  `cd sonar-ml/perception && pytest`, and `cd lidar/mapper && pytest`.
- How the areas relate (coordinate frames, formats, overlap):
  [sonar-ml/docs/status.md](sonar-ml/docs/status.md) "Relation to the rest of EchoSense".
