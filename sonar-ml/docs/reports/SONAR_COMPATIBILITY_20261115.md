# Ryan / Charvik sonar contract - 2026-11-15

Reviewed commits: PR #8 a63ebf3, PR #6 594c24f, codex/ultrasonic-scan fedd00c.
No firmware changes, physical serial operations or real ultrasonic validation.

## On-wire intersection

- Physical sensor identity/model is not sent by the firmware. Assign it explicitly
  in the host adapter. PR #6 adds sensor/session IDs and ordered host sequence.
  Mapper currently treats it as one optional phone-mounted HC-SR04 channel.
- Firmware prints positive decimal meters with three digits, or literal `timeout`,
  one newline-terminated record at 115200 baud; a startup `# hcsr04...` banner
  is also emitted. Ping interval 65 ms (~15.4 Hz); echo wait up to 25 ms.
- No device timestamp/sequence. PR #6 assigns host-receive Unix milliseconds with
  `timestamp_basis=host_receive_unix_ms`. Mapper uses host monotonic seconds for
  freshness (max age .35 s); its LiDAR frames have separate phone capture times.
  Do not equate these clocks without an explicit timebase/alignment strategy.
- PR #6 meters-line parsing accepts decimal syntax only, rejects exponent, zero,
  negative and nonfinite input; missing readings are null, never zero meters.
  Mapper float parsing also accepts exponent notation. Firmware's normal output
  is in their intersection. Startup/garbage is ignored/counted by mapper; PR #6
  emits explicit invalid events. A timeout is explicit in PR #6; mapper collapses
  missing/out-of-range/stale to no_sonar. Invalid mapper lines may leave the last
  valid reading fresh until its .35 s age limit expires.
- Configure PR #6 limits to 0.03 to 4 m to match mapper acceptance; its generic
  default .001 to 50 m is not HC-SR04 calibration. Serial mode requires verified
  model, modality, explicit baud, sensor ID and limit flags. Verification flag
  records operator authorization; it does not verify wiring or physics.
- Firmware carries no provenance. Test fixtures must remain synthetic; physical
  source designation is a host responsibility. PR #6 observations retain units,
  timestamp basis and calibration state. Mapper has `meta.sonar.synthetic`, but
  its outer simulation/replay map envelope still hard-codes live (see sprint report).

## Frames and model compatibility

A scalar range is a cone measurement, not a measured XYZ point. PR #6 keeps
`coordinate_frame=unregistered`, `sensor_pose=null`, calibration unverified.
The trainable forest instead needs SonarFrame v0.2 clusters of XYZ + SNR in
sensor-local forward/left/up meters. It cannot classify raw HC-SR04 scalar lines.
The mapper's optional fusion uses depth + known/assumed camera pose and configured
mount/aim offset to project approximate axis markers. Those remain hypotheses;
validate mount/angle and timing before claiming a located reflector. The forest
is not called by fusion and cannot validate it.

Mapper is the serial owner when physical fusion is demonstrated. PR #6 and the
codex branch's browser Web Serial capture must not open the same board at once.
A shared readout would require one owner forwarding observations with provenance;
there is no existing mapper -> range_observation publisher. Do not build a second
reader or treat `meta.sonar` as an already valid PR #6 envelope.

## Ports and codex branch

4173 = Node viewer; 8765 = mapper /ws JSON feed; 8770 = live binary phone /depth;
8780 = mapper dense HTTP + /map. Simulation does not listen on 8770.
Run an independent range sidecar on 8766 with `--range --port 8766 --origin
http://127.0.0.1:4173`, using the existing PR #6 checkout, and set both publisher
and panel URLs accordingly. Do not start the combined launcher alongside mapper:
it duplicates both 4173 and 8765.

`codex/ultrasonic-scan` adds five-reading Web Serial acquisition and a separate
sonar-forest training script; it does not publish the mapper or PR #6 protocols.
Its baud dropdown defaults to 9600; select 115200 for this firmware. Allow for
startup banners before starting a five-reading batch. No codex changes were
copied into this sprint.

## Executed software acceptance

`scripts/check-sonar-contract.py` passed eight synthetic cases through the actual
PR #6 ObservationBuilder/encoder and mapper parser. Cases: 1.234, .03 and 4 m,
timeout, nan, zero, banner, exponent input. Actual submitted low-limit text was
`0.030`, matching firmware syntax. No physical device was opened.

From repo root, using an interpreter with current mapper installed:

```powershell
$env:PYTHONPATH=(Resolve-Path lidar/mapper/src).Path
sonar-ml/.venv/Scripts/python.exe -B scripts/check-sonar-contract.py --range-root <PR6-worktree>/websocket-bridge --out sonar-ml/data/new-contract-result.json
```

Output refuses to replace an existing file. Expected: 8 cases pass. This verifies
parsing/schema intersection, not serial transport or sensor accuracy.

## Minimum test Ryan should run after hardware is ready

1. Confirm actual board/model, compiled pin selection, power/logic compatibility,
   wiring and mounting against his hardware guide. This sprint did none of those.
2. With only the mapper owning serial, verify newline records at 115200, count
   about 15 pings/s, and confirm no unit scaling error on a tape-measured flat
   wall at 1 m and 2 m. Record raw lines and configured extrinsics.
3. Induce no echo and unplug/reconnect: within .35 s mapper should report
   no_sonar, never a new zero-distance marker. Current mapper serial thread stops
   after unplug; restart acquisition deliberately. PR #6's mock-tested reconnect
   loop is more capable but has not been exercised on the physical controller.
4. Check wall alignment and one real phone scan. Validate a suspected additional
   reflector against physical ground truth; a sonar/LiDAR disagreement does not
   establish glass or safe space. Reject stale or uncertain-pose observations.
5. Record `.esd` plus sonar sidecar and replay; inspect time alignment, provenance,
   geometry and Room analysis. Do not call replay or simulation live. Keep the
   real recording as demo backup. Coordinate exact file/interface changes with
   Rishi and Akshath rather than replacing their active server/viewer files.
