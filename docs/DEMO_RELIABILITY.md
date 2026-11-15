# Mapper demo reliability handoff

This patch is stacked on PR #8 (`sonar/hcsr04-fusion`,
`a63ebf3fb022efa9ac91140aae7e88510638f33a`). It changes metadata and viewer
connection state, not mapping, classification, firmware or model weights.
PR #9 remains experimental; retain the existing production baseline. Room
analysis still uses the existing JavaScript geometry rules, not the forest.

## Ownership and review

Akshath: review `index.html`, `src/main.js`, `src/library.js`,
`src/mapper-adapter.js` and `src/room-plan.js` before integration.
Rishi: review `lidar/mapper/src/lidar_mapper/server.py` and `__main__.py`.
Ryan: review sonar metadata semantics and the hardware contract below.
No owner branch, completed combined-viewer worktree or model-sprint worktree
was edited. Do not copy an entire older mapper/server over a newer team version.

Refs fetched again on 2026-11-15: PR #6 `594c24f`, integration/demo / PR #7
`25a05e4`, sonar/hcsr04-fusion / PR #8 `a63ebf3`, model sprint / PR #9
`3421ff3`, viewer/lidar-integration `9a0b592`, codex/ultrasonic-scan `fedd00c`.
The separate databricks-pipeline branch `4f2bef7` has overlapping mapper edits;
it was inspected and not merged. This patch targets PR #8 for a focused review.

## Behavioral changes

- The existing `sonar_frame` v0.1 envelope, v0.2 point rows, axes, units and
  mapping/classification algorithms are retained. `source` describes delivery
  (`live`, `simulated`, `recorded`); `acquisition_source` describes original
  acquisition. The existing vocabulary `recorded` means original acquisition
  unknown when used in the latter field, and the viewer says so explicitly.
- Raw `.esd` depth headers already retain `source`: `sim` is synthetic;
  `lidar`/`arkit` are the phone's reported acquisition sources. Other/empty
  legacy sources stay unknown. Provenance covers the accumulated map: a later
  phone-labelled frame cannot erase simulated/unknown contributions. This is
  source metadata, not cryptographic proof that a device was present.
- `sim` explicitly selects simulated delivery. `fake-phone` through the live
  server remains live transport with simulated acquisition. Replay always
  selects recorded delivery and retains known depth acquisition provenance.
- Sonar's existing `synthetic` flag is retained. Legacy sonar sidecars contain
  only sequence/range, so their original acquisition is unknown even when the
  accompanying depth source is known. `meta.sonar.acquisition_source` makes
  that limitation explicit; no source is inferred from the other sensor.
- The adapter propagates validated provenance. Map badges, saved snapshot
  badges and the exported floor plan distinguish simulation, replay and
  unknown original acquisition. Simulated analysis/PNG says SIMULATED DATA.
- Losing or explicitly disconnecting the mapper WebSocket preserves the last
  geometry, colors, hits, classifier result and sonar marker history. The map
  and plan say historical; connection loss is visible, active indication is
  removed, and the range readout becomes unavailable. A failed reconnect does
  not erase that room. The next valid connection gets a fresh mapper session.
- Mock geometry remains available as initial preview and explicit Mock preview
  selection. It never replaces an established mapper room on disconnect.
  Archived maps do not show the background connection's active sonar readout.
- Unknown areas remain unobserved, never established empty or safe. The
  existing Room analysis caveat and classifiers are unchanged.

## Windows launch, no Bash or hardware

Use this isolated branch/worktree, not the completed combined-viewer checkout.
On this machine: `C:\Users\charv\EchoRescue-demo-reliability-local`.
An existing compatible environment was reused without installing packages:
`C:\Users\charv\EchoRescue-pr8-preflight-local\.venv\Scripts\python.exe`.

Terminal 1, repository root:

```powershell
node serve.js
```

Terminal 2, same root (substitute your isolated Python environment):

```powershell
$python = 'C:\Users\charv\EchoRescue-pr8-preflight-local\.venv\Scripts\python.exe'
$env:PYTHONPATH = (Resolve-Path lidar/mapper/src).Path
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
& $python -u -B -m lidar_mapper sim --frames 80 --serve --sonar-sim --viewer-points 50000
```

Open http://127.0.0.1:4173/; select **Sonar / Preview** and connect to
`ws://127.0.0.1:8765/ws`. Expect Simulated LiDAR map, Simulated sonar, agreement
then sonar_closer/magenta markers. Open Room analysis and download the PNG:
both carry simulation attribution and the unknown-space caveat. Stop only the
mapper you started: expect Connection lost, historical map retained and sonar
unavailable. Restart that command and Connect: expect a new simulated session.
Choose Mock preview explicitly after disconnect if the sample room is wanted.

Port owners: 4173 Node static viewer; 8765 mapper viewer `/ws`; 8780 mapper
dense HTTP + `/map`; 8770 binary phone `/depth` only in `serve` mode (unused by
`sim`/`replay`). Viewer Origin allowlist already includes localhost and 127.0.0.1
on 4173/5173/3000. Do not run another bridge or combined launcher on these ports.
Check conflicts without killing other processes:

```powershell
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object LocalPort -In 4173,8765,8770,8780 |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

The finite simulation/replay keeps serving its final map until stopped. This
patch handles viewer WebSocket loss; it does not add a phone heartbeat or
timeout for a connected mapper that continues to serve its last snapshot.
Do not interpret a connected socket as evidence of continuing phone capture.
The separately served dense viewer's existing UI is outside this patch; only
its HTTP/binary transport is covered here. Use the main viewer for attribution.

## Re-run verification after a team push

Fetch and review the new diff first. Create a new checkout for a different
baseline; do not reset any existing dirty worktree. The smoke runner starts
only its own local processes, refuses occupied ports, stops only its own PIDs,
and writes new timestamped reports/screenshots/PNG/recording fixtures under
`.venv/reliability/`. A nonzero exit, `completed: false`, or missing assertion
is not a pass. Keep failed and successful runs; do not overwrite old evidence.

```powershell
$python = 'C:\Users\charv\EchoRescue-pr8-preflight-local\.venv\Scripts\python.exe'
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
$env:ECHO_PYTHON = $python
$env:ECHO_PLAYWRIGHT_MODULE = 'C:\Users\charv\EchoRescue-pr8-preflight-local\.venv\browser\node_modules\playwright\index.mjs'
node scripts/demo-reliability-smoke.mjs
```

For a fresh machine only, create a local environment and install missing
dependencies there; no system-wide software is required by this patch:

```powershell
py -m venv .venv
$python = (Resolve-Path .venv/Scripts/python.exe).Path
& $python -m pip install -e 'lidar/mapper[dev,sonar]' -e 'websocket-bridge[test]' -e 'sonar-ml/perception[dev,lakehouse]'
npm.cmd --prefix .venv/browser install --no-package-lock playwright@1.65.1
$env:ECHO_PYTHON = $python
$env:ECHO_PLAYWRIGHT_MODULE = (Resolve-Path .venv/browser/node_modules/playwright/index.mjs).Path
```

The Windows smoke uses installed Edge (channel msedge). It installs no browser
or system software. Other platforms can supply ECHO_BROWSER_CHANNEL and an
already installed Playwright browser. Root Node tests need no npm packages.

## Fresh executed evidence, 2026-11-15

- Node v24.19.0: 49 passed, 0 failed, 0 skipped.
- Mapper: 41 passed, 0 failed, 1 skipped (Windows lacks POSIX termios/pty).
  Includes real binary `/depth` -> worker -> viewer `/ws` handler exchange on
  ephemeral ports with synthetic input, plus source/replay/mixed-map cases.
- Bridge: 130 passed, 0 failed, 0 skipped.
- Perception: 37 passed, 0 failed, 1 optional Spark skip (pyspark absent).
  Existing unit fixtures only; no model-sprint retraining or promotion.
- Browser smoke: 47 passed, 0 failed, complete; zero page errors. Actual
  mapper JSON stream mounted, agree/sonar_closer markers, Room analysis on
  20,715 map points, real PNG download, dense packet 2,279,048 bytes,
  failed/successful reconnect, explicit preview, synthetic/unknown replay,
  saved-map attribution and hidden background telemetry. All four ports
  released afterward. This extends the recovered earlier preflight rather
  than treating its old 6/4 results as evidence for the patch.
- Eight synthetic PR #6/mapper contract cases passed by reusing PR #9's
  `scripts/check-sonar-contract.py` against the existing PR #6 checkout. No
  serial port opened. Re-run from a PR #9 script checkout with PYTHONPATH
  pointing to this branch's mapper, `--range-root <PR6>/websocket-bridge`
  and a new `--out <result.json>` path.
- Python 3.14.4; pytest 9.2.0, numpy 2.5.4, scipy 1.18.1, sklearn 1.9.1,
  pyarrow 26.0.1, pandas 3.1.1, websockets 17.4, pyserial 3.5;
  Playwright 1.65.1. Imports and pip check passed; no AppControl/DLL failure
  recurred. No installation was needed.
- Local retained evidence: `.venv/mapper-final-*/pytest.log`,
  `.venv/node-final-*/node.log`, `.venv/bridge-*/pytest.log`,
  `.venv/perception-*/pytest.log`, `.venv/sonar-contract-*.json`, and
  `.venv/reliability/2026-11-15T08-16-23.131Z/report.json` with screenshots
  and the actual downloaded PNG. Earlier 38-check run retained too.
  Generated assets/environments are ignored, not committed.

## Remaining owner checks

Ryan: firmware newline decimal meters or literal timeout at 115200 baud,
~15 Hz (65 ms interval); mapper accepts 0.03-4 m and expires readings at
0.35 s host-monotonic age. PR #6 uses host-receive Unix milliseconds and
explicit sensor/session IDs; configure matching HC-SR04 bounds. These clocks
are not interchangeable with phone capture timestamps. Mapper must be the
only serial owner for fusion. There is no existing mapper-to-PR6 range
observation publisher. An independent range server may use 8766, but must not
open the same board; the codex Web Serial UI defaults to 9600 and must be set
to 115200 by its owner. No configuration was changed in that active branch.

Verify board/pins/firmware build, units at tape-measured distances, timeout,
unplug/restart, mount translation/aim/cone, pose uncertainty and clock alignment
on hardware. Mapper's serial thread currently stops on unplug; it does not
reconnect automatically. A disagreement marker is an approximate hypothesis,
not a calibrated spatial reflector or proof of glass/clearance. No hardware
performance, calibration or firmware compilation is claimed by these tests.

Rishi: real phone on Mac -> `/depth` -> main viewer -> Room analysis/PNG,
including dark-room tracking, source values, reconnect, recorded backup and
timestamp/mount alignment with Ryan. Synthetic socket tests do not validate
iOS capture, Xcode signing, local-network permissions or real drift.

Akshath: review the small overlapping UI edits against his next push. Check
map/source labels, historical state, saved-map badge, export footer and
explicit preview in the intended presentation browser. Coordinate newer mapper
edits with Rishi; merge decisions remain with the owners.

Software-only simulated demo: GO on this branch with explicit simulation
labels. Real-device demo readiness remains unverified. Do not deploy PR #9's
experimental model or claim that synthetic sonar fusion is calibrated hardware.
