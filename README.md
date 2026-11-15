# EchoSense

EchoSense is a spatial memory prototype for controlled search-and-rescue
planning demos. Its viewer shows surfaces observed by an iPhone LiDAR scanner.
The UI starts with **Mock data**, a modeled living room and simulated readings.

> **Sensor change (Nov 14):** the sonar hardware is no longer available. The
> live sensor is now an iPhone's LiDAR scanner. See
> [iPhone LiDAR](#iphone-lidar-live-sensor). The sonar simulation, ML and
> acoustic scanner remain in the repo and still run on simulated data.

## Run locally

Use Node.js 20 or later.

```sh
node serve.js
```

Open `http://127.0.0.1:4173/` in a WebGL-capable browser. There are no packages
to install. Stop the static development server with Ctrl+C.

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

## iPhone LiDAR (live sensor)

`ios/` holds a SwiftUI app that reads the iPhone LiDAR depth map and pushes
points to the bridge, which relays them to this viewer.

```
iPhone app  --ws /ingest-->  websocket-bridge --lidar  --ws /ws-->  viewer
```

```sh
node serve.js
cd websocket-bridge
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -B -m sonar_bridge --lidar --origin http://127.0.0.1:4173
```

Build the app from `ios/EchoSenseLiDAR.xcodeproj` and enter the laptop address
printed by the bridge. In the browser, select **iPhone LiDAR** in **Sensor feed**,
then **Start session**. Leave the address at `ws://127.0.0.1:8765/ws` when the
browser runs on the bridge laptop. The phone and laptop need to be reachable
on the same trusted network. See [ios/README.md](ios/README.md) for signing,
installation and phone settings.

- Use **Live** on the phone for a phone-relative depth view. Choose **Room map**
  to see the phone's accumulated observations. In this mode, scan a fixed
  object, turn away, and check that its points remain. The browser shows
  connection status, ARKit tracking, mean depth confidence out of 2, and the
  number of retained points. Blank areas are unknown; even observed surfaces
  do not establish a safe or fully searched room.
- **Pause display** freezes the view and skips frames until resumed.
  **Disconnect** keeps the latest view for inspection or saving. **Clear view**
  clears this browser's copy and holds it empty until you resume. When you
  resume, a connected phone can repopulate it from its own map. Reset the
  Room map on the phone to reset the collection itself.
- **Save snapshot** keeps the latest view and up to 12 one-second samples from
  this browser session in **Saved Maps**. Open the snapshot and use the replay
  timeline to inspect it. **Open LiDAR replay** also accepts a local JSONL file
  containing captured browser relay envelopes, one per line in capture order
  (up to 16 MB). It does not accept the raw phone messages or sonar NPZ
  manifests. Browser snapshots and replay files require no cloud service.
- No phone required for a transport check: run `python -B fake_phone.py --fps 3`
  in `websocket-bridge/` while the LiDAR relay runs. Expect 403 points and the
  **Synthetic LiDAR · controlled demo** badge. This fixture is phone-relative.
  For a browser-only check, open
  [the synthetic Room map JSONL](test/fixtures/lidar-room-synthetic.jsonl)
  with **Open LiDAR replay** and press **Replay**. Over four seconds, the
  wall remains as a second wall and an obstacle come into view.

The checkout's [relay format](websocket-bridge/PROTOCOL.md#live-lidar-relay---lidar-added-nov-14)
uses `/ingest` and `/ws` with a LiDAR-tagged bridge envelope. The adapter in
`src/lidar.js` converts its `[forward, left, up]` coordinates to
`[-left, up, -forward]` in meters. Native ARKit world XYZ can use the renderer's
Y-up axes unchanged. The relay does not include a camera transform or an
origin/session ID. The viewer therefore replaces its copy with each phone
snapshot. It will need the agreed session-aware stream to draw a real scanner
path or accumulate individual frames safely across movement. The frontend
path and bounded observation buffer accept normalized, session-tagged
observations, but the current relay supplies neither.

Before judging, validate the physical iPhone build, check a tape-measured
object and the expected up/forward directions, change to Room map and verify
retention while turning away, then save and replay that real scan. The local
synthetic test does not verify the physical iPhone or its metric accuracy.

## Backend handoff

To use the team's sonar WebSocket bridge, start it in a second terminal from
the repository root using Python 3.11+:

```powershell
Set-Location websocket-bridge
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -B -m sonar_bridge --origin http://127.0.0.1:4173
```

Open `http://127.0.0.1:4173/`, select **Sonar / Preview** and click **Connect**. The default address is
`ws://127.0.0.1:8765/ws`. Match `--origin` to the exact frontend host and port
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

## Verify

```sh
node --test
```

The tests cover preview payload conversion, malformed or oversized points,
decoder injection and disconnect, replay sample selection, and cell-based
change detection. For visual verification, load the page
and switch between all three camera and render modes. Change the vertex cap
and point size, enable Grid and RF rings, and try orbit, pan, and zoom.
At a phone width the controls start collapsed and can be opened above the
viewport. The browser check used a local WebSocket fixture to verify geometry
replacement, telemetry, invalid message handling and disconnect recovery.
