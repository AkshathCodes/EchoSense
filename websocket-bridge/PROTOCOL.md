# ECHO WebSocket envelope 0.1 ? PROPOSED, NOT an approved team standard

Endpoint: `ws://127.0.0.1:8765/ws` (localhost IPv4 only). One UTF-8 JSON text
message per frame; no client commands, handshake subscription, or binary payloads.
Each connection independently starts at sequence zero; EOF closes with code 1000.
Sequence counts sent frames, not global capture identity. Reconnect restarts replay.
Field names and envelope version remain subject to coordination with Akshath.

```json
{
  "protocol_version": "0.1",
  "type": "sonar_frame",
  "sequence": 0,
  "timestamp": 0.0,
  "source": "simulated",
  "acquisition_source": "simulated",
  "frame": {
    "format_version": "0.2",
    "meta": {
      "format_version": "0.2",
      "source": "synthetic",
      "sensor_id": "SIMULATED-wall-demo",
      "tilt_deg": 0.0
    },
    "points": [[2.0, 0.0, 0.0, 5.0]]
  },
  "detections": null
}
```

## Semantics

- `timestamp`: original capture timestamp in seconds. Simulation uses synthetic
  capture time (demo: sequence/10); it is NOT Unix wall-clock time. Replay pacing
  is fixed FPS, not capture-time spacing. Changing FPS does not rewrite timestamps.
- `source`: delivery source: `simulated`, `recorded`, or `live`. NPZ replay is
  `recorded`; direct synthetic data is `simulated`.
- `acquisition_source`: original source, mapped `synthetic` -> `simulated`;
  `recorded` and `live` remain as supplied by the producer. Replaying synthetic
  data never hides that it was simulated. The bridge cannot verify producer truth.
- `frame`: point-only transport projection of SonarFrame v0.2, NOT a replacement
  for the full SonarFrame file format. Volume, grid, labels, and instances are
  not transported. `meta` and point values are retained without rotation,
  normalization, classification, or correction.
- `points`: `[N,4]` arrays `[x,y,z,intensity]`. **X forward, Y left, Z up**,
  meters, acoustic-center origin, level body frame per v0.2. Intensity is
  **SNR** (amplitude/frame noise floor), nonnegative and NOT limited to [0,1].
  The bridge does not level sensor points; it expects already compliant points.
- SonarFrame grid/code angles are radians; `meta.tilt_deg` is degrees.
  Detection `azimuth_deg` and `elevation_deg` are degrees. Positive azimuth is left.
- `detections`: `null` means unavailable/not run; it does NOT mean no objects.
  Otherwise it is the **complete original detections v0.1 document**, with
  `format_version`, `frame`, `model`, and `detections`. An empty detections array
  means the supplied model document reports no detections.

## Detection document, unchanged v0.1

`frame` contains `timestamp`, `source`, `sensor_id`, `scene_id`, `conditions`,
`n_points`, as produced by Rishi's `frame_detections_dict`. Frame association
must match capture timestamp, source, identifiers, conditions, and point count.
`conditions` dictionaries in SonarFrame metadata use their `name` for this check.
Each detection contains:

- `id`, `class`, `class_id`, `confidence`, `probs`
- `centroid`, `bbox_min`, `bbox_max`: three coordinates, meters, X forward/Y left/Z up
- `range_m`, `azimuth_deg`, `elevation_deg`
- `n_points`, `mean_intensity`
- optional `gt_class`, only for labeled data, never live

Class IDs: 0 wall, 1 doorway, 2 furniture, 3 debris, 4 person, 5 noise.
`person` is a person-sized-object prediction; confidence is uncalibrated.
All six documented class probabilities are preserved. No probabilities,
confidence, boxes, labels, angles, or ranges are recomputed or invented.
Invalid input is rejected rather than repaired. JSON formatting may change;
numerical values do not. Integration fixtures are not real classifier detections.

## Bounds and validation

Maximum 20,000 points, 256 detections, and 2,000,000 UTF-8 bytes per message.
Coordinates, intensity, timestamps, and detection scalars must be finite numbers;
booleans are not numbers. Rows have exactly four entries; boxes/centroids three.
Negative intensity/range, invalid probabilities/confidence, inverted boxes,
unknown detection fields/versions/classes, and mismatched frame association are
rejected. Empty point arrays are allowed. Only SonarFrame v0.2 and detections
v0.1 are currently accepted; there is no silent format upgrade or downsampling.
Unknown transport versions should be rejected by consumers.

Default 10 FPS, configurable >0 through 30 FPS. At most four clients. Each
connection holds one current message with backpressure, no producer queue, and
no catch-up bursts. Snapshot replay and demo restart independently for each
client; this is not a shared live acquisition hub. Send stalls >5 seconds close
with 1013, as does exceeding client capacity. Invalid/unavailable source closes
with 1011 and a generic reason; no raw input data is logged. Normal disconnection
releases the source. Small incoming-message buffers are capped; clients should
send no application messages. No request/command protocol is implemented.

## Origins

Default exact allowed Origins:
`http://localhost:5173`, `http://127.0.0.1:5173`,
`http://localhost:3000`, `http://127.0.0.1:3000`.
`--origin` replaces defaults; repeat for several exact frontend origins.
Unknown, `null` (file://), and absent Origins are rejected by default.
`--allow-no-origin` explicitly permits non-browser clients without Origin.
The smoke client sends an allowed Origin. WebSocket Origin checks, rather than
HTTP CORS response headers, restrict browser handshakes; this isn't authentication.
There is no LAN binding option, TLS, or production deployment configuration.

## Source evidence inspected read-only

Archive: `C:/Users/charv/Downloads/madhacks-sonar-main.zip`, prefix
`madhacks-sonar-main/`:

- `AGENTS.md` and `docs/status.md`
- `docs/interfaces/sonar-frame.md`
- `docs/interfaces/detections.md`
- `perception/src/sonar_perception/frame.py`
- `perception/src/sonar_perception/detections.py`
- `perception/src/sonar_perception/inference.py`
- `perception/src/sonar_perception/sources/recorded.py`

This workspace changes none of these contracts or source files.

## Live LiDAR relay (`--lidar`), added Nov 14

`python -m sonar_bridge --lidar` replaces the per-client replay with a relay.
Differences from everything above:

- Binds `0.0.0.0` (override with `--host`) so a phone on the LAN can connect.
  No TLS and no authentication.
- `ws://<laptop>:8765/ingest`: one producer at a time, must send no `Origin`
  header (native app). A second producer is closed with 1013.
- `/ws`: same Origin allowlist as before. Every viewer gets the same newest
  frame. A viewer that connects late gets the last frame immediately. A slow
  viewer skips frames. `sequence` counts frames accepted from the phone and
  is shared by all viewers.
- A phone message that fails validation is dropped and counted; the
  connection stays open.

Phone message, one JSON text frame each:

```json
{"type":"lidar_frame","version":"0.1","timestamp":51234.50,
 "sensor_id":"iphone-lidar","tracking":"normal","reference":"sensor",
 "points":[[1.20,-0.05,0.00,2]]}
```

- `points`: `[x,y,z,confidence]`, same axes as sonar (X forward, Y left, Z up,
  meters). `confidence` is ARKit depth confidence 0, 1 or 2. It travels in the
  intensity slot and is not an SNR. Same 20,000 point and 2 MB limits.
- `reference`: `sensor` means relative to the phone for this frame, leveled
  with gravity. `world` means accumulated in the ARKit session frame (origin
  at the phone's starting position).
- `tracking`: `normal`, `limited` or `not_available`.
- `timestamp`: ARKit frame time in seconds since device boot.

The bridge wraps it in the unchanged 0.1 `sonar_frame` envelope with
`source` and `acquisition_source` both `live`, `detections: null`, and
`frame.meta` = `{format_version:"0.2", source:"live", sensor_id, tilt_deg:0,
modality:"lidar", tracking, reference}`. Viewers tell LiDAR from sonar by
`frame.meta.modality`.
