# Akshath handoff: simulation provenance and disconnected mapper

## Scope and model decision

Experimental branch `backend/synthetic-model-sprint` is based on PR #8 a63ebf3.
RETAIN BASELINE. Candidate challenge macro-F1 .5929 -> .6925, standard .8222 ->
.7666; three forest seeds. The trained forest is not used by live Room analysis,
which remains the existing JavaScript geometry rules. Do not activate the model.
No viewer, mapper, hardware or production inference files were changed here.

Latest refs checked for this handoff: integration/demo 25a05e4,
sonar/hcsr04-fusion a63ebf3, codex/ultrasonic-scan fedd00c,
viewer/lidar-integration 9a0b592. They have not advanced since the experiment.
Newer databricks-pipeline 4f2bef7 changes mapper internals; coordinate with Rishi
rather than overwriting his server/CLI from an older branch.

## Reproduce the two demo defects

From a PR #8 checkout with mapper dependencies installed, Windows terminals:

```powershell
# Terminal 1, repo root
node serve.js
# Terminal 2, repo root, using the activated local Python environment
python -u -B -m lidar_mapper sim --frames 80 --serve --sonar-sim --viewer-points 50000
```

Mac alternative: `SONAR_SIM=1 bash scripts/run-lidar.sh --mapper-sim`.
Do not also start the bridge or combined-viewer launcher on the same ports.

1. Open http://127.0.0.1:4173/, choose Sonar / Preview, connect to
   ws://127.0.0.1:8765/ws. Wait for agree then sonar_closer and magenta markers.
2. Open Room analysis, then Download PNG. Sonar text says Simulated sonar,
   but the map badge says LiDAR map, the wire declares live acquisition and
   the exported plan lacks SIMULATED DATA.
3. Stop only the mapper started in terminal 2. The scan is replaced by the mock
   living room, with Mock data and Connection failed visible. This is automatic
   fallback, not an unlabelled mock feed; it loses the last scan and analysis.

## Exact file-level changes for the owners

- Rishi/Ryan: `lidar/mapper/src/lidar_mapper/server.py`,
  `LiveMapper.snapshot`, currently lines 159/171: remove hard-coded live from
  envelope/meta for sim/replay. Add state with default live for compatibility.
- Rishi/Ryan: `lidar/mapper/src/lidar_mapper/__main__.py`, LiveMapper construction
  in serve and sim/replay (97/123): assign actual delivery/acquisition mode;
  preserve known recording provenance and never invent live/real for unknown
  original acquisition. Keep the existing protocol version and envelope shape.
- Akshath: `src/mapper-adapter.js`, `createMapperSession().decode`, line 135:
  stop overriding delivery/acquisition to live; carry validated envelope values
  into the existing mapper and source metadata. Reuse the current decoder.
- Akshath: `src/main.js`, `showScanSource` (208-230): choose simulated/replay/live
  map badge and live indicator from provenance, not merely a connected socket.
  In `showRoomAnalysis` (235-246), pass the mapper's simulation state instead of
  the current false default. Keep archive source attribution consistent (527).
- Akshath: `src/main.js`, `status` (326-376): extend last-scan preservation to
  mapper input before the generic state clear. Retain points/colors/hits and
  analysis, label them historical/disconnected, remove live indication and
  clear or explicitly stale-label sonar telemetry. Mock mode should require an
  explicit choice after a real/mapped feed has been established.

A backend-only metadata patch is insufficient: the adapter and plan also
hard-code live/non-simulated. Coordinate these small changes; no UI redesign,
classifier replacement, new model integration or protocol rewrite is needed.

## Acceptance criteria after the next integration push

- Simulation: actual mapper /ws updates, surface classes, simulated map/sonar
  labels, magenta marker, Room analysis and PNG with simulation attribution.
- Replay: replay badge and correct original acquisition where known; never live.
- Disconnect: last map remains, connection loss is visible, no live badge or
  fresh-looking sonar value, and no automatic replacement with mock geometry.
- Existing LiDAR, archive and classification tests continue passing. Unknown
  space remains unknown, never clear/safe. Real phone/hardware checks remain.

Current evidence: unit suites pass (Node 41, perception 47 +1 skip, mapper
20 +1 skip, bridge 130), eight synthetic serial cases pass. The saved browser
baseline is 6 passing and 4 failing readiness assertions. Its strict disconnect
wording assertion fails even though Connection failed is visible; do not claim
that the error is completely hidden. No new training was run for this handoff.

## Sonar interface reminders

Use 115200 baud, decimal meters/newline or timeout, one serial owner. The codex
Web Serial dropdown defaults to 9600. PR #6's generic limits need matching to
mapper's 0.03 to 4 m acceptance; timestamps use different host clock bases.
There is no mapper-to-range-observation forwarder. A range sidecar needs its own
8766 port; mapper uses 8765/8780, phone input 8770, static viewer 4173. Physical
mount/aim, firmware build, calibration, real serial reconnect and live phone
Room analysis still require team hardware validation. See the detailed
[sonar contract](SONAR_COMPATIBILITY_20261115.md).
