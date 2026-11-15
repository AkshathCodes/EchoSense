# ECHO isolated Python WebSocket bridge

Proposed integration transport for Rishi's sonar data and Akshath's existing
frontend. No frontend, model, hardware interface, or old spatial package is
included or imported. See PROTOCOL.md before connecting the frontend.

## LiDAR mode

Real iPhone LiDAR uses its own endpoints and message format, kept apart from
the sonar path. Full contract: [LIDAR_PROTOCOL.md](LIDAR_PROTOCOL.md).

```powershell
# live: phone publishes to /lidar/publish, browser reads /lidar/view
.\.venv\Scripts\python.exe -B -m sonar_bridge --lidar --record session.jsonl --origin http://127.0.0.1:4173
# replay a recording to /lidar/view at 3 frames a second
.\.venv\Scripts\python.exe -B -m sonar_bridge --lidar-replay session.jsonl --origin http://127.0.0.1:4173
# no phone: SYNTHETIC publisher, labeled as such in every frame
.\.venv\Scripts\python.exe -B fake_phone.py
```

On macOS or Linux the interpreter is `.venv/bin/python`. `--lidar` binds all
interfaces so the phone can connect and prints the address to enter in the
app; use `--host` to bind one address. No TLS, no authentication.
`sonar_bridge/lidar.py` holds validation, the hub, recording and replay;
`tests/test_lidar.py` covers them.

## Windows PowerShell setup and launch

```powershell
Set-Location 'C:\Users\charv\EchoSense-websocket-local'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test,recorded]'
.\.venv\Scripts\python.exe -B -m sonar_bridge
```

Connect the existing frontend to `ws://127.0.0.1:8765/ws`. The default demo is
explicitly SIMULATED: a deterministic 45-point wall at x=2 meters, SNR=5,
synthetic capture timestamps, no classifier execution (`detections: null`).
Press Ctrl+C to stop. No activation or PowerShell policy changes are needed.
The basic runtime needs only websockets; `pip install -e .` suffices without
recorded replay or tests. Python 3.11+ is required.

If Akshath uses another local port, replace the Origin allowlist explicitly:

```powershell
.\.venv\Scripts\python.exe -B -m sonar_bridge --origin 'http://localhost:8080'
```

Origins specify the webpage's HTTP origin, not the ws:// server endpoint.
Other options: `--fps 5`, `--allow-no-origin` (explicit Python-client opt-in).
Network API implementation follows the official websockets asyncio documentation:
https://websockets.readthedocs.io/en/stable/reference/asyncio/server.html

## Verify

From this workspace:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider --basetemp .test-tmp
.\.venv\Scripts\python.exe -B .\smoke_test.py
```

Stop any existing bridge before the smoke test: it starts the real CLI on 8765,
reads three messages with a Python client, disconnects, and stops its child
server. Tests use ephemeral loopback ports and simulated NPZ/detection fixtures.
Only the timeout unit test uses a fake stalled connection for deterministic timing.

## Recorded replay (optional numpy, no trained model)

Create a JSONL manifest beside saved Rishi SonarFrame v0.2 `.npz` files and
associated original detections v0.1 `.json` documents. One line per capture,
in desired acquisition order:

```json
{"frame":"scene_00000.npz","detections":"detections_00000.json"}
{"frame":"scene_00001.npz"}
```

```powershell
.\.venv\Scripts\python.exe -B -m sonar_bridge --manifest '.\recordings\manifest.jsonl' --fps 5
```

The manifest and recording data are user-supplied; no real captures are bundled.
Paths must resolve within the manifest directory; no filename-based association
is guessed. Reads are lazy, one capture at a time. NPZ data uses `allow_pickle=False`.
NPZ compressed size is capped at 16 MB and declared expanded size at 64 MB; JSON
files/manifest lines at 16 MB. The replay reader projects only points, timestamp,
and metadata; it does not validate or load the unused volume/grid as SonarFrame.
Detections must match the supplied frame. EOF closes normally. Replay source is
`recorded`, while acquisition_source and original metadata preserve provenance.
This is read-only replay, not a recorder or a directory watcher.

## Actual SonarFrame adapter boundary

`sonar_bridge.protocol.encode_sonar_frame(frame, sequence, detections_document)`
accepts an actual SonarFrame by duck typing (`points`, `timestamp`, `meta`). NumPy
points are converted with `.tolist()` after shape/size checks. Pass the unmodified
output of Rishi's `frame_detections_dict(frame, detections, model_name)` or None.
This does not import his package, run inference, invent classifier values, or
apply rotations. The basic tests don't require that package or any model.

A future adapter can produce validated messages through this function and supply
an iterator factory to `Bridge`. Actual async live acquisition, synchronization
across clients, and nonblocking disk I/O are deferred. Current bounded local
replay performs file reads on the event loop; it targets small demo recordings.
No actual hardware/model stream or Akshath frontend has been integration-tested.

## Files and ownership

- `sonar_bridge/protocol.py`: envelope, validation, SonarFrame adapter
- `sonar_bridge/sources.py`: deterministic demo and lazy NPZ/JSON replay
- `sonar_bridge/server.py`: local endpoint, origin filtering, pacing and cleanup
- `sonar_bridge/__main__.py`: CLI
- `tests/`: protocol, source and lifecycle verification
- `smoke_test.py`: real CLI/client localhost smoke test

Everything belongs to this isolated workspace. No Git repository is initialized.
The archive was inspected read-only; no Rishi/Akshath project files were copied
or modified. This bridge doesn't alter SonarFrame v0.2 or detections v0.1.


## Independent sonar / range integration

The range path carries individual distance observations, not a point cloud.
It does not infer sensor pose, fuse distances into LiDAR, run a classifier,
or claim that an unobserved area is clear. The existing `/ws` sonar stream
and optional LiDAR service retain their original schemas.

Run these commands from this worktree's `websocket-bridge` directory in
separate PowerShell terminals (Python 3.11+ and Node 22+ for the smoke test):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test,serial]'
.\.venv\Scripts\python.exe -B -m sonar_bridge --range --lidar --origin http://127.0.0.1:4180 --range-record recordings/range-session.jsonl
.\.venv\Scripts\python.exe -B range_readout.py
.\.venv\Scripts\python.exe -B -m sonar_bridge.range_adapter --fixture fixtures/range-synthetic.txt --format meters-line
```

Open http://127.0.0.1:4180/ and connect before starting the fixture.
The bridge, adapter and readout default to port 8765; a custom bridge
`--port` also requires the adapter `--url` and readout URL to match.
The static readout serves only its three public assets, never recordings.
Use a new recording filename for each capture: existing files are refused.
For the existing LiDAR viewer, also allow its origin with
`--origin http://127.0.0.1:4173`. Range mode binds loopback by default;
explicitly select `--host` if a verified LAN device needs access.

Replay without a sensor:

```powershell
.\.venv\Scripts\python.exe -B -m sonar_bridge --range-replay recordings/range-session.jsonl --origin http://127.0.0.1:4180
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider
.\.venv\Scripts\python.exe -B range_smoke_test.py
```

Observations preserve sensor/session IDs, increasing sequence, timestamp and
clock basis, original units and raw value, normalized meters, availability,
and acquisition provenance. Missing/invalid returns have null distance.
Replay retains acquisition provenance and is separately labeled REPLAY.
The bounded processing window defaults to five samples, at least three valid
samples and a valid majority, with at most 0.35 m spread. A missing latest
reading withholds the median. Optional outlier filtering and tape-reference
error are explicit policy settings saved in the recording, not confidence
or accuracy claims. Limits: 32 sensors, 128 sessions per bridge lifetime;
restart the bridge for a fresh session budget. Recording limits are 10,000
observations or 16 MiB; failures stop forwarding the affected publication.

Hardware remains BLOCKED until the exact sensor and controller models,
datasheets, power/logic voltages, wiring, baud rate, output format, units,
range limits and timeout semantics are verified. No port is auto-probed.
`--serial` requires `--hardware-verified`, `--sensor-id`, `--sensor-model`,
`--modality`, `--baud`, `--min-m`, `--max-m` and an explicit `--format`.
That flag records operator authorization; it does not verify the hardware.
Current serial formats are positive decimal meters per newline, or structured
JSON with `distance`, `units` (m/cm/mm), and `status` (valid/timeout/no_return).
An optional controller timestamp must include its timestamp basis. Other
firmware protocols require an adapter after their format is confirmed.
Physical acquisition, tape-distance checks, disconnect recovery on an actual
controller and sensor-to-LiDAR pose calibration still need hardware testing.
