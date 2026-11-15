# EchoSense

ECHO RESCUE maps an indoor space with an iPhone Pro's LiDAR, without relying
on visible light, and keeps what it saw. It builds a 3D map as the operator
moves, sorts it into floor, walls and objects, and draws a floor plan that
marks what was never observed. The use case is simulated search-and-rescue
planning.

It does not see through walls or smoke, detect people behind obstacles, or
make a phone an operational firefighting device. Not observed never means safe.

```
iPhone Pro LiDAR + motion sensors      Mac mapper (lidar/mapper)        Viewer (src/)
capture app (lidar/ios)            ->  position from depth + IMU    ->  surface classes,
no camera images used                  dense voxel map, recording       room analysis, floor plan
```

This is the path that has run on a real phone
([log](sonar-ml/docs/log/2026-11-14-iphone-lidar-pivot.md)). Full darkness
has not been tested yet.

## Quick start

Needs Node 20+ and Python 3.11+ (macOS ships 3.9: `brew install python@3.12`).
A real scan also needs an iPhone Pro with the capture app from `lidar/ios/`
([build steps](lidar/README.md)).

On macOS or Linux, one command sets up and starts the mapper and the viewer:

```sh
scripts/run-lidar.sh --mapper                  # live: phone streams to the mapper, session recorded
scripts/run-lidar.sh --mapper-sim              # no phone: the mapper's SIMULATED room
scripts/run-lidar.sh --mapper-replay lidar/mapper/recordings/<file>.esd
```

Open `http://127.0.0.1:4173/`, set **Sensor feed** to **Sonar / Preview**
(address `ws://127.0.0.1:8765/ws`), and click **Connect**. The badge reads
**LiDAR map**, points are coloured by surface class, and **Room analysis**
draws the floor plan. **Open dense map** shows the mapper's full-density view.

The mapper viewer uses the existing **LiDAR surface forest v1** weights on
the accumulated map. Classification runs locally in a browser worker. Live
depth points keep their separate overlay color. Room analysis, saved mapper
scans, and PNG exports use the predictions for that map, with footprints,
class totals, and separate ceiling and uncertain-return layers. The viewer
uses the geometric classifier if trained inference fails. The weights were
trained on synthetic scans and have not been validated on real mapper data.
If the phone stops sending depth or the mapper disconnects, the viewer keeps
the last observed map as historical and marks current sonar readings unavailable.

With an HC-SR04 strapped to the phone ([guide](hardware/hcsr04/README.md)),
`SONAR_PORT=/dev/cu.usbmodem1101 scripts/run-lidar.sh --mapper` adds a sonar
cross-check: the viewer shows the sonar and LiDAR distances side by side and
marks possible sonar-only surfaces in magenta. Reflections from glass can
produce this result, but the marker does not identify the material.
`SONAR_SIM=1 scripts/run-lidar.sh --mapper-sim` shows it with simulated
readings. The HC-SR04 and XIAO nRF52840 Sense passed a Windows serial bench
test with a synthetic LiDAR publisher. Combined operation with a real iPhone
and sensor alignment still need testing.

With nothing running, `node serve.js` shows the viewer on built-in mock data.

### Two LiDAR paths, one port

| Path | Phone app | Laptop | Viewer feed | State |
|---|---|---|---|---|
| **Mapper (demo)** | `lidar/ios/` | `lidar/mapper/` | Sonar / Preview, `/ws` | Run on a real phone |
| Bridge (fallback) | `ios-lidar/` | `websocket-bridge/ --lidar` | iPhone LiDAR, `/lidar/view` | App never compiled; synthetic frames only |

Both serve the viewer on port 8765, so run one at a time. The bridge path adds
a coverage map, scanner path and audio cues that the mapper path does not
feed yet. `scripts/run-lidar.sh` with no argument, `--fake` or `--replay`
starts the bridge path.

## Bridge path: LiDAR spatial memory

```sh
node serve.js
cd websocket-bridge
python3 -m venv .venv && .venv/bin/pip install -e .   # needs Python 3.11 or later
.venv/bin/python -B -m sonar_bridge --lidar --record session.jsonl --origin http://127.0.0.1:4173
```

Open `http://127.0.0.1:4173/`, select **iPhone LiDAR**, and click **Connect** (the address defaults to
`ws://127.0.0.1:8765/lidar/view`). Then publish frames from the phone
([ios-lidar/README.md](ios-lidar/README.md)) or, with no phone, from the
labeled synthetic publisher: `.venv/bin/python -B fake_phone.py` in `websocket-bridge/`.

What the viewer adds on top of the point cloud:

- **Persistence.** Points are kept in a 5 cm voxel grid (`src/spatial-memory.js`),
  capped at 120,000 cells, so geometry stays after the scanner turns away.
- **Scanner path.** The green trail and marker show the scanner's recorded
  positions. The path breaks across tracking loss and paused display updates.
- **Coverage map.** A plan view in 25 cm cells: *Surface* (a return landed
  there above floor level), *Seen through* (a sensor ray crossed it), and
  *Not observed*. A cell counts as seen if one ray crossed it at any height,
  which is weaker than "empty". Not observed means no measurement.
- **Tracking honesty.** Frames sent while ARKit tracking is not normal are
  counted and not stored. A new phone session clears the map instead of
  merging two origins.
- **Surface classes.** A geometric classifier (`src/room-classifier.js`) labels
  every retained point as floor, wall, ceiling or object and colours the cloud
  by class (the "Surface classes" render mode, on by default for LiDAR). It is
  a set of rules on room geometry, not a trained network: floor and ceiling
  are the busiest height layers at the bottom and top, a wall is a 10 cm
  column filled over at least 1.2 m of height, and everything else is an
  object. Tall cabinets and doors count as walls.
- **Room analysis.** The button in the LiDAR panel draws a labelled floor plan
  (`src/room-plan.js`): walls, floor seen, each object with a letter and its
  height, the scanner path, a 1 m scale bar, and black for not observed.
  **Download PNG** saves it. Objects are measured, not identified.
- **Audio cues** (off by default): session started, tracking lost and
  restored, phone connected and lost, snapshot saved, replay complete.
- **Pause display** skips browser updates while the bridge keeps recording.
  **Clear map** holds the browser map empty until you resume. **Disconnect**
  preserves the last scan for **Save snapshot** and review in Saved Maps.

The source badge reads **Live LiDAR** only for `source: arkit_scene_depth`
frames in live mode. Synthetic frames read **Simulated LiDAR**, and bridge
replays read **LiDAR replay**.

Replay a recorded session:

```sh
.venv/bin/python -B -m sonar_bridge --lidar-replay session.jsonl --origin http://127.0.0.1:4173
```

Connect to that replay bridge, or choose the bridge's JSONL file (up to 16 MB)
with **Open LiDAR replay**. Use **Room analysis** during scanning or replay to
inspect the current observations and export the floor plan. Saved maps retain
surface colors and keep different ARKit coordinate sessions separate.

How well it does, on simulation only (`test/scan-simulator.js` ray-casts a
furnished room at the phone's sampling density with range noise and stray
returns): 91 to 96% of points labeled correctly across a typical 40 s scan, a
12 s scan, a scan that never looks up, and a noisy one. The sofa, table and
crate are found with heights within about 5 cm; footprints come out up to
30 cm too large. Known weak spots: a wall that has only been partly scanned
is listed as an object until more of it is seen, the bottom 10 cm of walls
and furniture is labeled floor, and anything taller than 1.2 m (a person, a
door, a cabinet) is labeled wall. It has not been scored on a real scan.

Not verified: the iPhone app has never been compiled, and no real LiDAR frame
has passed through this pipeline. Everything above was exercised with
synthetic frames only.

## Viewer controls

- **Orbit / Camera / Top** switch between a cutaway, eye-height view, and
  overhead view. Drag to orbit, Shift-drag or right-drag to pan, and scroll
  to zoom. In Top view, dragging pans. On a touchscreen, pinch to zoom.
- With the canvas focused, use arrow keys to rotate, Shift + arrows to pan,
  + and − to zoom, and 0 to reset the current view.
- **Render mode** switches between cyan points, natural-color points, and
  triangular wireframe. The wireframe has cyan, ice, and height-based tints.
- **Max vertices** caps the rendered points or line vertices. **Point size**
  adjusts points only. **Frame skip** skips geometry uploads in socket mode
  while retaining telemetry on the preview fixture. For sonar, it skips
  whole frames so detections stay paired with their own point cloud. In
  mock mode it slows telemetry refresh.
- **Grid** draws a one-meter coordinate grid. **RF rings** shows three
  simulated anchors and their coverage rings. The amber outline shows the
  estimated zone when the source supplies an estimate above the UI threshold.
- **Height slice** shows a 44 cm band centered at the selected height.
  **Estimate trail** shows recent confident estimates and leaves gaps when
  the estimate was missing. The trail is disabled for sonar frames because
  the bridge supplies sensor-relative positions. **Camera** adds a heading
  and overhead map.

## Saved Maps

Open **Saved Maps** to find two labeled mock scans of the same room. The
second pass includes returns that the first missed near the chair and
bookcase. Select both thumbnails' **Compare** checkboxes and choose
**Compare** to open the synchronized cameras. **Change overlay** uses
0.25 m cells to highlight returns in the later scan that have no matching
cell in the earlier scan. Gray returns do not establish that a surface was
removed or that an unobserved area was clear. The overlay is available only
for scans with a shared coordinate frame. The current socket decoder has
no alignment metadata, so live captures can be viewed side by side with the
overlay disabled.

Use **Save snapshot** in the scanner to capture the current geometry,
telemetry and thumbnail. The library supports renaming, deleting, and
filtering by name or data source. Selecting a thumbnail reopens that map
in the scanner. Use **Replay** or scrub the timeline to see the stored
frames and estimate gaps. The two demo maps show a synthetic scan build;
new snapshots retain the most recent 12 one-second samples plus the
capture frame. A snapshot with just one frame still opens in the viewer.

The archive uses IndexedDB in this browser, scoped to the address and port.
Reloading the same URL keeps the maps. Clearing this site's browser data
removes them. Maps are not synced or uploaded. The scanner on the Scan
tab keeps receiving socket messages while a saved map is open.

## Verify

```sh
node --test                                         # viewer, adapter, spatial memory, classifier
cd lidar/mapper && .venv/bin/python -m pytest       # mapper
cd websocket-bridge && .venv/bin/python -m pytest   # bridge
```

The tests cover LiDAR frame decoding, voxel filtering, coverage cells, room
classification on a labeled synthetic room, audio cue
rate limiting, preview payload conversion, malformed or oversized points,
decoder injection and disconnect, replay sample selection, and cell-based
change detection. For visual verification, load the page
and switch between all three camera and render modes. Change the vertex cap
and point size, enable Grid and RF rings, and try orbit, pan, and zoom.
At a phone width the controls start collapsed and can be opened above the
viewport. The browser check used a local WebSocket fixture to verify geometry
replacement, telemetry, invalid message handling and disconnect recovery.

## Repository layout

| Path | What | Owner |
|---|---|---|
| `lidar/` | **Demo path.** iPhone capture app, Mac mapper, dense viewer, Databricks export | Rishi |
| `ios-lidar/` | Fallback ARKit app for the bridge path, never compiled | Ryan |
| `websocket-bridge/` | Python bridge, [LiDAR protocol](websocket-bridge/LIDAR_PROTOCOL.md), record and replay | Charvik |
| `index.html`, `style.css`, `serve.js`, `src/` | Web viewer and LiDAR rendering | Akshath |
| `src/mapper-adapter.js`, `src/spatial-memory.js`, `src/room-classifier.js`, `src/room-plan.js`, `src/audio-cues.js` | Mapper adapter, spatial memory, room classification, floor plan, audio cues | Ryan |
| `test/` | Viewer tests, including the scan simulator | viewer and Ryan |
| `docs/` | [Demo plan](docs/DEMO.md) | Ryan |
| `hardware/hcsr04/` | HC-SR04 sonar: firmware, [wiring and mounting guide](hardware/hcsr04/README.md) | Ryan |
| `scripts/` | Setup and run helpers | shared |
| `acoustic/`, `sonar-ml/` | Earlier sonar work, simulated data only | Ryan, Rishi |

Rules for working in the repo are in [AGENTS.md](AGENTS.md).

### Branches

- `main`: what the team has agreed to demo. Merge only after telling the team.
- `develop`: integrated work waiting to go to `main`.
- Your own work: `<area>/<short-name>`, for example `ios/pose-fix`,
  `bridge/replay-speed`, `viewer/trail-colour`, `memory/change-detection`.
  Open a pull request into `develop`.

# Earlier work

The sections below describe the mock scene and the sonar and acoustic
pipelines built before the switch to LiDAR. They still run, on simulated data.

## The mock scene

The UI starts with **Mock data**, a modeled living room. The earlier sonar
simulation, ML and acoustic scanner are still in the repo and still run on
simulated data only.

### Run the viewer alone

Use Node.js 20 or later.

```sh
node serve.js
```

Open `http://127.0.0.1:4173/` in a WebGL-capable browser. There are no packages
to install. Stop the static development server with Ctrl+C.

## Geometry and reference choices

The references use several rendering styles and show different interiors. The
default scene follows the cyan living-room cutaway: two exposed walls, a
doorway on the left, framed picture and three-seat couch, low open-shelf table
in front, window on the right, then an armchair and bookcase. The eye-height
wireframe uses triangulated surfaces, with a partial ceiling and bright
edges. Natural color and RF/grid layers come from the corresponding reference
images. The compact upper-right controls follow the point-cloud viewer panel.

The images provide no scale or measured scan. The model assumes an
8.6 × 6.4 × 3.15 m room and uses Y-up coordinates in meters. Furniture is
modeled from visible silhouettes and relationships, with rounded cushions,
shelves, individual books, and a lamp. Front and left walls are open for the
cutaway. The wireframe and points are generated from surfaces at startup.

## Sonar bridge handoff

To use the team's sonar WebSocket bridge, start it in a second terminal from
the repository root using Python 3.11+:

```powershell
Set-Location websocket-bridge
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -B -m sonar_bridge --origin http://127.0.0.1:4173
```

Open `http://127.0.0.1:4173/`, select **Sonar / Preview**, and click
**Connect**. Match `--origin` to the exact frontend host and port
if you use a different URL. The default bridge stream is a simulated 45-point
wall with no model detections. For NPZ recordings with optional detection JSON,
see [bridge setup and manifest format](websocket-bridge/README.md). On normal
replay completion the final frame remains available to inspect and save.

`src/feed.js` owns the connection lifecycle. `openFeed(url, options)` receives
an injected `decode(payload)` function plus `onFrame`, `onStatus` and optional
`onInvalid` callbacks. It returns a disconnect function. The viewer consumes
geometry and settings and has no WebSocket dependency. The static HTTP server
and Python bridge run separately.

The Connect control accepts the bridge's [v0.1 wire envelope](websocket-bridge/PROTOCOL.md)
with v0.2 SonarFrame points. `src/sonar.js` converts forward/left/up meters
to viewer coordinates `[-left, up, -forward]`. The viewer replaces each
sensor-relative frame because the bridge supplies no shared room pose.
The UI shows mean SNR and original capture time. The strongest person-class
detection supplies the existing estimate marker when it meets the UI
confidence threshold. These are acoustic model predictions. Simulated
acquisition remains labeled simulated, including on recorded replay.

The UI expects a partial snapshot with optional `points` (flat XYZ
`Float32Array`), `frame` (integer), `latencyMs` (number), and `target`
(`{ position: [x,y,z], confidence }` with confidence 0–1, or `null` to clear).
An omitted field retains its last value. A zero-length point array clears
geometry. Mesh and RF anchors are derived from the sample scene and are
available in mock mode.

The adapter also accepts the earlier preview fixture for local UI testing:

```json
{"frame":7,"latencyMs":22,"points":[[0,0,0],[1,1,1]],"target":{"position":[0,0,0],"confidence":0.71}}
```

## Acoustic Scan and Databricks

Open **Acoustic Scan** in the workspace navigation. **Try sample scan** opens
a labeled simulated room. Drag to orbit, move the You marker, or select an
echo group to see the straight-line distance to its closest sampled return.

On the scanning laptop, open Acoustic Scan on localhost. Use the built-in
speaker and mic, mark an origin and forward direction, and enter the
scanner's location, height, and aim for each set of five chirps. Heading
0° is forward and 90° is right. Start with a rigid panel at tape-measured
distances of 1 m and 2 m. For a room view, scan each surface from multiple
positions and at two heights with the same scene and surface names. These
names group returns for surface interpolation. Distances come from the
echo range and the entered scanner pose. The You marker is set manually.

The scanner previews the map immediately and offers **Download scan CSV**
and **Download room map**. To open on a phone over a trusted local network,
start the server with `HOST` set to `0.0.0.0` and open
`http://<laptop-LAN-address>:4173/acoustic/` in Safari. Keep microphone
capture on localhost. Use **Open map** on the phone or save the report at
`acoustic/room-map.json` and choose **Load shared map**.

1. Import `acoustic/aggregate.py` as a Python source notebook in Databricks.
2. Upload `acoustic/sample-scans.csv` to a Unity Catalog volume for the
   labeled simulation. For a measured run, use the CSV from Acoustic Scan.
3. Run the definitions and widget cells. Set `input_csv` and `output_json` to
   full paths such as `/Volumes/<catalog>/<schema>/<volume>/sample-scans.csv`
   and `/Volumes/<catalog>/<schema>/<volume>/room-map.json`. Run the remaining
   cells. The notebook shows scan coverage, rejection reasons, and range
   error for accepted poses with a tape reference.
4. Download `room-map.json` from the volume and open it in Acoustic Scan.

The same aggregation can run locally with Python 3.10 or later.

```sh
python acoustic/aggregate.py acoustic/sample-scans.csv acoustic/room-map.json
```

## Sonar ML (`sonar-ml/`)

Sonar simulation, 3D mapping, segmentation and object classification (wall,
doorway, furniture, debris, person) in Python. It currently runs on simulated
40 kHz sonar data and writes a detections JSON. Start with
[`sonar-ml/README.md`](sonar-ml/README.md) and
[`sonar-ml/AGENTS.md`](sonar-ml/AGENTS.md). Run its commands from `sonar-ml/`:

```sh
cd sonar-ml
python3 -m venv .venv && .venv/bin/pip install -e "perception[dev]"
cd perception && ../.venv/bin/python -m pytest
```
