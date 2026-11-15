# EchoSense contributor handoff

Start with [AGENTS.md](AGENTS.md) and the [README](README.md). Work from
`develop` on an area branch and coordinate before merging. See the Git log
for the exact state of the current checkout.

EchoSense is a controlled prototype for recording and reviewing spatial
observations. The browser can show a mock living room, the earlier sonar
stream, or observations from the iPhone LiDAR pipeline. No display of an
observed or unobserved area establishes that the room is safe.

## Local LiDAR flow

1. `ios-lidar/` publishes ARKit world coordinates, per-point depth confidence,
   pose, tracking state, and a session ID to `/lidar/publish`.
2. The Python bridge validates frames, distributes them on `/lidar/view`,
   and can record or replay them as JSONL. See the draft
   [LiDAR v1 protocol](websocket-bridge/LIDAR_PROTOCOL.md). The older sonar
   pipeline still uses its own `/ws` route.
3. The browser retains observations in a bounded voxel map, draws the
   scanner pose and segmented path, and distinguishes observed returns from
   unknown space. It keeps sessions and data sources separate. A display
   floor offset affects the scan, path, and pose together without changing
   distances.
4. Class colors and voxel support are archived with their scan. Room analysis
   draws a local floor plan from the current display sample and can export
   it as PNG. The geometry-based classifier sizes objects; it does not
   identify furniture or people.

`src/feed.js` owns transport, `src/lidar.js` owns the LiDAR viewer adapter,
`src/main.js` connects state and controls, and `src/viewer.js` renders.
Read the ownership table before editing bridge, iOS, or spatial-memory code.

## Verification

Use `node --test` at the repository root and run `pytest` from both Python
projects with their declared dependencies. To exercise the whole software
route without a phone, run the bridge with `--lidar --record session.jsonl`
and start `websocket-bridge/fake_phone.py` in a second terminal. Use the
browser's **Open LiDAR replay** to inspect the file, or serve it with
`--lidar-replay session.jsonl`. Keep the synthetic badge visible.

The iPhone build and real-world scale, orientation, and tracking still need
a physical acceptance test. Use a tape-measured wall or box and record a
short session that includes motion and a fresh coordinate origin. Keep
real and synthetic metrics separate.

The earlier sonar simulation and laptop audible-chirp experiments remain
under `sonar-ml/` and `acoustic/`. Their results do not validate ARKit
LiDAR performance. The legacy LiDAR relay used different endpoints and no
pose or session IDs; do not mix those recordings with v1.
