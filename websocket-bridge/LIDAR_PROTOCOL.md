# lidar_frame v1

Transport for real iPhone LiDAR data. Separate from the sonar envelope in
[PROTOCOL.md](PROTOCOL.md). This document is the source of truth: the phone
app, the bridge and the viewer all follow it. Change it here first, and tell
the team, before changing any of them.

**Status: draft written from the Nov 14 plan email. Charvik owns it and has not
yet reviewed this wording.**

## Endpoints

Start with `python -m sonar_bridge --lidar`. Port 8765.

| Path | Who | Rules |
|---|---|---|
| `/lidar/publish` | the phone | One publisher at a time; a second is closed with 1013. Must send no `Origin` header. |
| `/lidar/view` | browsers | Exact `Origin` allowlist (`--origin`). At most four viewers. Read only. |

`--lidar` binds `0.0.0.0` so a phone on the LAN can connect; set `--host` to
bind one address. There is no TLS and no authentication. The sonar path `/ws`
is not served in LiDAR mode.

## Frame

One UTF-8 JSON text message per frame, at most 1,000,000 bytes. Exactly these
fields, no others:

```json
{
  "type": "lidar_frame",
  "schema_version": 1,
  "session_id": "0B6F2C1E-5D0A-4C55-9E0B-0C2E5B3D9A11",
  "device_id": "iphone-1A2B3C4D",
  "sequence": 12,
  "timestamp": 51234.567,
  "source": "arkit_scene_depth",
  "coordinate_frame": "arkit_world",
  "units": "meters",
  "tracking": "normal",
  "camera_to_world": [1,0,0,0, 0,1,0,0, 0,0,1,0, 0.512,-0.031,-1.204,1],
  "points": [[0.500,-1.200,-2.003]],
  "confidences": [2]
}
```

| Field | Meaning |
|---|---|
| `session_id` | 1 to 64 printable characters. One per continuous ARKit world origin. The app issues a new one on launch, on New, after an interruption, and after relocalization. |
| `device_id` | 1 to 64 printable characters. |
| `sequence` | Integer from 0, strictly increasing within a session. |
| `timestamp` | ARKit frame time, seconds since device boot. Not wall-clock time. |
| `source` | `arkit_scene_depth` for real measurements. `synthetic` for test data, which must never be presented as real. |
| `coordinate_frame`, `units` | Always `arkit_world` and `meters`. |
| `tracking` | `normal`, `limited` or `not_available`. |
| `camera_to_world` | 16 numbers, column-major 4x4 rigid transform. Elements 12 to 14 are the camera position. Bottom row must be 0 0 0 1. |
| `points` | Up to 5,000 `[x, y, z]` in ARKit world coordinates. The app sends about 1,000 at 3 frames a second. |
| `confidences` | Same length as `points`. ARKit depth confidence: 0 low, 1 medium, 2 high. |

## Coordinates

ARKit world, gravity aligned: +Y up, origin at the phone's position when the
session started, -Z roughly ahead of the starting pose. Right-handed, meters.

- The app transforms depth samples into this frame and sends them.
- The bridge validates and forwards. It applies no rotation, scale or the
  sonar forward/left/up conversion.
- The viewer uses the values as is. Its one display-only change is a vertical
  lift that puts the lowest retained point on its y = 0 grid (`src/lidar.js`).
- Camera position and points share the same origin within a session.
- When `tracking` is not `normal` the app sends the pose and an empty `points`
  array. Consumers must not add geometry from such frames.

## Sessions

A new `session_id` means a new origin. The bridge drops its backlog for the
old session and the viewer clears its map. Sessions are never merged. A frame
whose `sequence` does not increase within its session is rejected.

## Status message (bridge to viewers only)

```json
{"type":"lidar_status","schema_version":1,"mode":"live","publisher_connected":true,
 "session_id":"...","recording":false}
```

Sent when a viewer connects and whenever the publisher connects, disconnects
or starts a new session. `mode` is `live` or `replay`.

## Validation and bounds

The bridge rejects, counts and skips a frame (the connection stays open) when:
it is not JSON, has missing or extra fields, has a wrong type or version, has
non-finite numbers, has a coordinate beyond 1,000 m, has mismatched array
lengths, exceeds 5,000 points or 1,000,000 bytes, or repeats a sequence.

Each viewer has a bounded outbox of 600 messages. When it is full the oldest
is dropped. A viewer that connects late receives the status message and then
the backlog (up to 600 frames) of the current session.

## Recording and replay

```sh
python -B -m sonar_bridge --lidar --record session.jsonl --origin http://127.0.0.1:4173
python -B -m sonar_bridge --lidar-replay session.jsonl --origin http://127.0.0.1:4173
```

`--record` appends every accepted frame as one JSON line. `--lidar-replay`
re-validates the whole file at startup, then plays it to each viewer from the
first frame at a fixed rate (3 a second, or `--fps`), sends nothing else, and
closes with code 1000 and reason `source complete`. Values are not changed, so
a replay of real data keeps `source: arkit_scene_depth` and a replay of
synthetic data keeps `source: synthetic`. The viewer labels both as replay.
