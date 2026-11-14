# ECHO isolated Python WebSocket bridge

Proposed integration transport for Rishi's sonar data and Akshath's existing
frontend. No frontend, model, hardware interface, or old spatial package is
included or imported. See PROTOCOL.md before connecting the frontend.

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
