# AGENTS.md — EchoSense monorepo

Map for AI agents and new teammates. Each area has its own docs; read the one
for the area you're changing before you change it.

| Path | What | Owner | Read first |
|---|---|---|---|
| [`ios-lidar/`](ios-lidar/) | iPhone ARKit LiDAR publisher (Swift, not yet compiled) | Rishi | [ios-lidar/README.md](ios-lidar/README.md) |
| [`websocket-bridge/`](websocket-bridge/) | Python bridge: LiDAR publish/view, record, replay; sonar replay | Charvik | [LIDAR_PROTOCOL.md](websocket-bridge/LIDAR_PROTOCOL.md) |
| repo root (`index.html`, `src/`, `serve.js`, `test/`) | Web viewer, LiDAR rendering (`src/lidar.js`), saved maps (Node 20+, no packages) | Akshath | [README.md](README.md) |
| `src/spatial-memory.js`, `src/audio-cues.js`, [`docs/DEMO.md`](docs/DEMO.md) | Voxel memory, coverage map, audio cues, demo plan | Ryan | [README.md](README.md) "LiDAR spatial memory" |
| [`acoustic/`](acoustic/) | Audible-chirp laptop scanner, Databricks scan aggregation | Ryan | [README.md](README.md) "Acoustic Scan and Databricks" |
| [`sonar-ml/`](sonar-ml/) | Python sonar simulation, 3D mapping, segmentation, classification; research, decisions (ADRs), logs | Rishi | [sonar-ml/AGENTS.md](sonar-ml/AGENTS.md), then [sonar-ml/docs/status.md](sonar-ml/docs/status.md) |

## Rules
- Stay in your area; changes to another area go through its owner.
- No unilateral pushes or merges to `main`. Work on a branch and coordinate before integrating.
- The LiDAR schema and coordinate rules change in `LIDAR_PROTOCOL.md` first, announced to the team.
- Synthetic data stays labeled synthetic. Only real ARKit measurements are called real LiDAR.
- `main` should pass all suites: `node --test` (root),
  `cd websocket-bridge && pytest`, and `cd sonar-ml/perception && pytest`.
- How the areas relate (coordinate frames, formats, overlap):
  [sonar-ml/docs/status.md](sonar-ml/docs/status.md) "Relation to the rest of EchoSense".
