# ECHO RESCUE demo plan

Owner: Ryan. Draft: nothing here has been rehearsed with the real phone yet.

## One-line pitch

ECHO RESCUE turns live spatial observations into persistent, reviewable
environmental intelligence for simulated search-and-rescue planning.

## Setup (10 minutes before)

1. Laptop on the phone's Personal Hotspot.
2. `node serve.js`, then the bridge with `--lidar --record demo.jsonl`.
3. Phone app: Laptop, enter the address the bridge prints, Connect.
4. Browser: Connect. Tick **Audio cues**. Badge should say waiting for phone,
   then update when Start scan is pressed.
5. Props: one table or chair in open floor, one doorway or corner to leave
   unscanned on purpose, one box to move for the stretch step.

## Sequence (about 3 minutes)

| Step | Do | Say | Viewer shows |
|---|---|---|---|
| 1 | Start scan, sweep the near wall and the table | "This is real LiDAR from the phone, about a thousand points three times a second." | Points appear; badge reads Live LiDAR |
| 2 | Walk two or three meters, keep scanning | "ECHO records where the scanner has been." | Orange path grows; Scanner path meters rise |
| 3 | Turn your back on the first wall | "The phone no longer sees that wall. ECHO still has it." | First wall stays |
| 4 | Point at the coverage map; leave the doorway unscanned | "Dark cells have no measurement. We never call them clear." | Dark region behind the doorway |
| 5 | Cover the camera for two seconds | "When tracking fails, ECHO says so and stores nothing." | Tracking cue; skipped-frame count rises; no smear |
| 6 | Stop scan, Save snapshot, open Saved Maps | "The exploration can be reviewed later." | Saved map with replay |
| 7 (stretch) | Restart the bridge with `--lidar-replay demo.jsonl`, Connect | "Same session, replayed from the recording." | Badge reads LiDAR replay |

The moment to land: step 3 into step 4. A LiDAR viewer shows what the sensor
sees now. ECHO shows what was seen, from where, and what was never seen.

## If something fails

| Failure | Fallback |
|---|---|
| Phone cannot reach laptop | Check hotspot; otherwise run `--lidar-replay` of a real recording made earlier and say it is a replay |
| Tracking keeps dropping | More light, slower motion, torch on, point at textured surfaces |
| App will not build or crashes | Replay a real recording if one exists. If none exists, show the synthetic publisher and say plainly that it is simulated |
| Browser shows nothing | Check the bridge's `--origin` matches the page address exactly |

Record a real session as soon as the phone works, and keep that file. A
synthetic run is not a substitute and must not be described as a scan.

## Limits to state out loud

- Phone LiDAR reaches about 5 m and does not see through walls, smoke or fog.
- Position tracking uses the camera, so it needs some light and texture.
- "Seen through" means one ray crossed a cell at some height. It is not proof
  the cell is empty.
- Observed geometry is not proof an area is safe or fully searched.
- No person or object detection runs on LiDAR data.

## Not built

- Region-change detection between two LiDAR sessions.
- Viewer-side button to start a bridge replay (replay is a bridge command).
- Headgear mockup.
