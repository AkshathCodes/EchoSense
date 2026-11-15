# Stage 2A: depth capture freshness

Small stacked patch on Stage 1 `6d6ebbee58c9a14b9b1596ae16271df161f5f910`
(PR #12). Target: `viewer/main-demo-reliability`, not main. Existing worktrees,
PR heads, trained weights/worker, geometry, sonar fusion, firmware, iOS and
Databricks remain untouched. No dependency was added or installed.

## Contract and behavior

The existing v0.1 `/ws` envelope and point rows are unchanged. Optional
`frame.meta.capture` adds:

```json
{"mode":"live","state":"stalled","age_s":3.201,"stall_after_s":3.0}
```

- `mode`: live, simulated, replay, unknown. Uses existing conservative
  acquisition attribution; recorded delivery is always replay. A simulated
  source transported through the live server is still simulated.
- `state`: waiting (no successful depth yet), active, stalled, disconnected
  (observed phone socket close), complete (finite simulation/replay ended).
- `age_s`: seconds since the last **successfully ingested** depth frame,
  computed with the mapper host's monotonic clock, or null before any success.
  Snapshot generation, outgoing sequence counters, malformed messages and
  failed mapping never refresh it. No phone/host clocks are subtracted.
- `stall_after_s`: configurable finite positive threshold; default **3 seconds**
  allows roughly 30 missed frames at the normal 10 Hz. State becomes stalled
  strictly after the threshold. A new successful ingestion resumes active.

When capture stalls, the mapper keeps serving snapshots. The main viewer says
Mapper connected / stalled, labels its last room historical, preserves geometry,
colors, trained report and marker history, removes active indication, and marks
sonar unavailable because the depth cross-check is not current. Source close
is separate from viewer-to-mapper loss; the latter retains Stage 1's Connection
lost behavior and the last reported capture metadata rather than inventing a
phone disconnect. Simulated and replayed completion explicitly becomes historical.

Saved scans retain their analysis and capture metadata; existing archive/PNG
attribution includes historical/stalled/completed state. Classification and
fusion calculations are unchanged. Older producers without the optional block
remain readable, with freshness unavailable and no positive phone-live indicator.
Older viewers may ignore the additive metadata and will not gain this indication.

## Launch and verification

Use this isolated checkout: `C:\Users\charv\EchoRescue-capture-freshness-local`.
Run `node serve.js` in terminal 1. In terminal 2 at the same root:

```powershell
$python = 'C:\Users\charv\EchoRescue-pr8-preflight-local\.venv\Scripts\python.exe'
$env:PYTHONPATH = (Resolve-Path lidar/mapper/src).Path
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
& $python -u -B -m lidar_mapper sim --frames 80 --serve --sonar-sim --capture-stall-seconds 3
```

Select Sonar / Preview at http://127.0.0.1:4173/, connect to
ws://127.0.0.1:8765/ws. The finite simulation becomes complete/historical while
the mapper remains connected. The same flag configures `serve` and `replay`.
Do not start another mapper or bridge on 8765/8780; live `serve` also owns 8770.

Fresh tests (no unrelated lengthy bridge/perception suites rerun):

```powershell
node --test
& $python -B -m pytest lidar/mapper/tests -q -ra
$env:ECHO_PYTHON = $python
$env:ECHO_PLAYWRIGHT_MODULE = 'C:\Users\charv\EchoRescue-pr8-preflight-local\.venv\browser\node_modules\playwright\index.mjs'
node scripts/demo-reliability-smoke.mjs
```

Executed: Node **62 passed, 0 failed, 0 skipped**; mapper **54 passed, 0 failed,
1 skipped** (POSIX termios/pty unavailable on Windows). Browser **85 assertions
passed, 0 failed**, including the Stage 1 checks, actual browser forest output
matching original main, forced geometric fallback, sonar/magenta markers,
simulation/replay completion, and a controlled connected source that pauses,
stalls, resumes and closes before the mapper is stopped. All depth bytes are
synthetic; the phone-source header fixture tests semantics, not physical capture.
The test uses a 1-second threshold to keep execution short; the 3-second default
and configurable boundary are covered by deterministic mapper tests.

Final retained browser evidence:
`.venv/reliability/2026-11-15T14-13-34.705Z/report.json` plus
`capture-stalled.png`, PNG downloads and process logs. The earlier successful
run remains separate. Unit logs: `.venv/capture-tests-20261115-080836/node.log`
and `.venv/mapper-20261115-081045/pytest.log`.

Each browser run preserves new timestamped logs/screenshots/recording fixtures
under `.venv/reliability/`. Unit logs are under `.venv/capture-tests-*` and
`.venv/mapper-*`. No previous evidence is overwritten. The smoke refuses busy
ports and stops only processes it created. Stage 1's demo remains passing.

## Limits and recommendation

This measures ingestion freshness, not device exposure time, tracking quality,
clock calibration or authenticity. Backlogged/repeated valid input can look
fresh; heavy processing/network delays can look stalled. Status arrives at the
viewer on its next accepted snapshot; this is not an independent watchdog for
a hung worker/event loop. Dense viewer UI is unchanged; the main EchoSense
viewer implements this indication. No real phone or hardware was operated.

Recommend owner review and merge before the demo: this closes a misleading
connected-but-static state without changing predictions or sensor algorithms.
Akshath reviews the small adapter/viewer additions; Rishi reviews metadata and
the conservative 3-second operational threshold. Keep the PR stacked on Stage 1
and merge nothing automatically. Further Stage 2 work is outside this patch.
