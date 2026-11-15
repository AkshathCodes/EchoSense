# Stage 1 compatibility plan

Verified baseline: main `86a767cbe8fbc4555ac9da0d592048c0af196484`, including
merged PR #11 (`integration/hcsr04-live` `6c9aa9a`). Source patch: draft PR #10
`9a75b0a9dc4869496036b1524be174bda58bd420`. PR #10 stays unchanged. This new
branch is `viewer/main-demo-reliability`; its review parent is current main.
No PR #6/#8 merge, PR #9 activation, retraining, firmware, iOS or Databricks edits.

Compatibility decisions recorded before implementation:

1. Mapper server/CLI metadata logic is unchanged between PR #10's parent and
   current main. Port the delivery/acquisition tracking and legacy-unknown
   handling, retaining the v0.1 envelope, v0.2 point rows, geometry and sonar
   fusion. Existing hardware fixes in PR #11 remain untouched.
2. `src/mapper-adapter.js` now awaits the trained classifier with a cached map
   and pending-job guard. Keep that code, `analysis`, `simulated`, colors,
   hit arrays and the busy-frame `null` sentinel. Add provenance validation
   and fields around it. Never restore PR #10's synchronous geometry decoder.
3. `src/main.js` must keep `createMapperClassifier()` and its browser worker.
   Share that classifier across fresh connection-specific adapter sessions,
   committing a session only on a valid frame. Preserve main's explicit
   `undefined` protocol fallback: `null` means skip, not sonar decode.
   Keep the historical session and its stored analysis on failed reconnect.
4. Main now saves `mapper.analysis` and enables archived mapper Room analysis.
   Keep that report and schematic export path. Add source/replay/history
   attribution, hide unrelated background telemetry, and use the displayed
   sample's sonar points when analysing an archive rather than a newer session.
5. `showRoomAnalysis` caches by analysis identity; attribution/history and
   sonar overlays can change without a new classifier report. Include those
   changes in redraw invalidation. Extend `drawRoomPlan` with an optional
   attribution footer; `drawLidarSchematic` already forwards its options.
   Do not replace the trained schematic with the old geometry-only plan.
6. Port the historical disconnect state, conservative live indicator and
   explicit Mock preview option. Retain current main's bridge/range readout,
   trained-inference fallback, source colors and other UI behavior.
7. Capture deterministic main classification labels/colors/report signatures
   before production edits. Run fresh Node, mapper, bridge, perception and
   adapted actual-browser tests, including worker success/failure and stale
   inference across disconnect/reconnect. Preserve timestamped evidence.

Ownership overlap: Akshath reviews viewer/adapter/library/export changes;
Rishi reviews mapper metadata and connection semantics. The additional
databricks-pipeline mapper/export changes remain unmerged and out of scope.
PR #11 reports physical HC-SR04 verification; this Stage 1 work performs only
software tests and makes no new physical-hardware or real-phone claims.

## Implementation and compatibility

The production diff is limited to mapper provenance, connection state, source
badges and an optional export footer. `src/main.js` and the adapter were edited
around current main's classifier integration, not replaced with old files.
The pending-job/reset guards and `null`/`undefined` distinction are retained.
Each connection has its own adapter and shares the existing trained worker.
Each accepted frame owns its analysis and sonar overlay; a skipped frame does
not publish an overlay. Archives retain that report/overlay for their own map.

The mapper accumulates source categories conservatively: any synthetic
contribution keeps the map simulated; live plus unknown stays unknown.
Original depth source survives raw recording/replay. Legacy scalar sonar
sidecars cannot establish their original source. The existing envelope uses
`source` for delivery and `acquisition_source` for original acquisition; the
existing value `recorded` in acquisition means unknown original source.
Missing legacy envelope provenance is also treated as unknown, never live.
Old saved maps with only `simulated: true` retain that known attribution;
`simulated: false` alone cannot establish real acquisition.

Disconnect/failed reconnect retains geometry, classes, stored report and
historical sonar markers, labels the map/PNG historical, removes active live
indication and invalidates the current sonar readout. New valid frames use a
new adapter session. Mock preview remains initial/explicit selection only.
Archived analysis uses its own trained report and markers even while a newer
connection runs. Attribution invalidates the export cache independently of
analysis identity and is forwarded through the existing trained schematic.

Unchanged from main: forest weights and features, prediction/analysis modules,
worker implementation, trained schematic, geometry rules, range readout,
bridge, archive storage, replay engine, point row representation and axes,
firmware, iOS, ML training and Databricks. No PR #6/#8 changes were merged again.
The forest file blob is unchanged: `469ad62e8c8a94f0a0552fb4c04a33e3c8085278`.

## Fresh verification

Executed on Windows, using Node 24.19.0 and the existing isolated Python 3.14.4
environment from `EchoRescue-pr8-preflight-local/.venv`. No dependencies were
installed or upgraded. `pip check` passed. No AppControl/DLL failure occurred.

- Unmodified main baseline: Node 49 passed, 0 failed, 0 skipped, before the port.
- Port Node suite: 60 passed, 0 failed, 0 skipped.
- Mapper Python: 41 passed, 0 failed, 1 skipped (POSIX pty/termios on Windows).
- Bridge Python: 204 passed, 0 failed, 0 skipped, including range integration.
- Relevant perception Python: 37 passed, 0 failed, 1 skipped (optional pyspark).
  Existing unit fixtures only, no training sprint or deployment.
- Actual Edge/Playwright browser smoke: 71 passed, 0 failed, completed, zero
  page errors on the normal path; the worker failure was intentionally injected
  on a separate test page. All four demo ports were released afterward.
- Existing `websocket-bridge/range_smoke_test.py`: PASS, five synthetic
  observations through CLI adapter/relay/JS decoder/history/record/replay,
  plus the existing sonar and LiDAR routes. Its legacy hardware-blocked footer
  describes the runner's scope; PR #11's reported physical checks were not rerun.

The fixed regression scene was captured from unmodified main before source
edits: 20 s, seed 17, 15 mm noise, 1% outliers, 3 fps. After repeated returns
and mapper-shaped rounding it contains 15,228 points. Main's trained counts
are [203 unclassified, 2106 floor, 9124 wall, 486 ceiling, 3309 object].
Labels, colors, geometry and full analysis hashes match exactly in both the
ported Node adapter and a real browser worker. The expected signatures are in
`scripts/fixtures/main-86a767c.json`; the deterministic generator is
`scripts/fixtures/mapper-regression.mjs`. No retraining was used to obtain them.
This is a fixed regression comparison, not a claim of real-data accuracy.

Acceptance scenarios 1-6: Node metadata tests, mapper `test_provenance.py`, and
actual simulated/replayed WebSocket frames exercise simulation, synthetic
sonar, live transport with synthetic acquisition, phone-source-header replay,
unknown recordings and mixed accumulated sources. All fixtures are synthetic,
including bytes carrying a `lidar` header to test real-acquisition replay labels.

Scenarios 7-12: the browser stops only its own mapper, verifies historical
geometry/analysis and inactive telemetry, tries a failed reconnect, reconnects,
selects Mock preview, downloads a PNG and opens saved trained maps. Archived
reports and their own sonar overlays are checked in IndexedDB and export.

Scenarios 13-16: actual module workers execute the original forest, compare
all four baseline signatures, show the trained schematic, then a separate page
blocks the worker and verifies geometric fallback. Another check holds an
actual worker result, disconnects, releases that result, and confirms historical
state survives before reconnecting through the shared worker. Existing tests
retain the orange live-depth and magenta sonar colors and pending/reset guards.

Evidence retained locally, never overwritten:
`.venv/main-baseline-20261115-074248/node.log`,
`.venv/main-baseline-fixed-fixture.json`,
`.venv/node-20261115-074641/node.log`,
`.venv/mapper-20261115-074641/pytest.log`,
`.venv/bridge-20261115-074641/pytest.log`,
`.venv/perception-20261115-074641/pytest.log`,
`.venv/range-smoke-20261115-075326.log`, and
`.venv/reliability/2026-11-15T13-50-00.702Z/report.json` plus screenshots,
downloaded PNG and synthetic recording fixtures. Generated evidence and
environments remain ignored; only the small deterministic expected signatures
and generator are committed.

## Reproduction, Windows PowerShell

Run these commands from the repository root, with the dev dependencies in `.venv`.
Terminal 1 at its root:

```powershell
node serve.js
```

Terminal 2 at the same root, reusing the tested isolated interpreter:

```powershell
$python = (Resolve-Path .venv/Scripts/python.exe).Path
$env:PYTHONPATH = (Resolve-Path lidar/mapper/src).Path
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
& $python -u -B -m lidar_mapper sim --frames 80 --serve --sonar-sim --viewer-points 50000
```

Open http://127.0.0.1:4173/, select Sonar / Preview and connect to
ws://127.0.0.1:8765/ws. Expect simulated map/sonar labels, class colors,
LiDAR surface forest v1, magenta markers and simulation-attributed analysis
and PNG. Stop only your mapper: historical map remains and sonar is unavailable.
Restart and connect to resume. Use Mock preview explicitly for the sample room.

4173 = Node viewer; 8765 = mapper `/ws`; 8780 = mapper dense HTTP and `/map`;
8770 = binary phone `/depth` in `serve` mode, unused by `sim`/`replay`.
The existing Origin allowlist includes localhost and 127.0.0.1 on 4173.
Do not start another mapper/bridge/combined launcher on the same ports.

For tests, stop only the demo processes you started, then from the same root:

```powershell
$python = (Resolve-Path .venv/Scripts/python.exe).Path
$env:PYTHONPATH = @((Resolve-Path lidar/mapper/src).Path,
  (Resolve-Path websocket-bridge).Path,
  (Resolve-Path sonar-ml/perception/src).Path) -join ';'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
& $python -B -m pip check
node --test
& $python -B -m pytest lidar/mapper/tests -q -ra
& $python -B -m pytest websocket-bridge/tests -q -ra
& $python -B -m pytest sonar-ml/perception/tests -q -ra
& $python -B websocket-bridge/range_smoke_test.py
$env:ECHO_PYTHON = $python
$env:ECHO_PLAYWRIGHT_MODULE = (Resolve-Path .venv/browser/node_modules/playwright/index.mjs).Path
node scripts/demo-reliability-smoke.mjs
```

Other machines may substitute their existing compatible isolated interpreter
and Playwright module. The browser smoke uses installed Edge on Windows,
requires no Bash and installs nothing. It checks occupied ports, stops only
its own PIDs, and creates a new timestamped artifact directory each time.
A missing assertion or `completed: false` is not a passing preflight.

## Readiness and Stage 2 boundaries

Stage 1 software simulation: GO on this branch, subject to Akshath/Rishi review.
PR #10, main and all other existing branches/worktrees remain unchanged.
GitHub must review this port against main, not PR #10's older PR #8 parent.

No new physical sensor, firmware, live iPhone, calibration or real-model
accuracy verification was attempted. PR #11 reports HC-SR04 hardware checks;
combined real iPhone + sonar and real-data classifier validation remain owner
tasks. Trained weights remain synthetic-trained and experimental PR #9 is not
activated. No Stage 2 hardware, labeling, Databricks or model work was started.

Existing limitations retained: a connected mapper can continue serving its
final snapshot (no new capture heartbeat); legacy sonar sidecars cannot recover
missing original provenance; scalar sonar markers are approximate hypotheses
until mount/pose/time alignment is validated. Dense-viewer UI attribution is
outside this port, although its HTTP/binary transport is tested. Unknown space
remains unknown, never established clear or safe.

Review questions: Akshath should confirm source/archived-map/export behavior
against upcoming UI work; Rishi should confirm source-header semantics and
coordinate the unmerged databricks-pipeline changes without replacing the
mapper wholesale. Those changes were not imported here. Neither owner approval
nor a real-device result is implied by a synthetic regression pass.
