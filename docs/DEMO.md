# ECHO RESCUE demo plan

Owner: Ryan. Nothing below has been rehearsed end to end on the real phone yet.

## One line

ECHO RESCUE maps a room with iPhone LiDAR without relying on light, keeps what
it saw, and shows what it never saw.

Use the same line in the README, the Devpost page and the pitch.

## Before judging: three things only a person with the phone can do

1. **Scan with the lights off.** The claim is "works without light" and it has
   not been tested. Do one scan lights on and one lights off in the same room.
   Export both with `--label lights=on` and `--label lights=off`. If the dark
   scan tracks worse, say so in the pitch with the numbers.
2. **Record the backup.** Keep the best real `.esd` from step 1. Check it
   replays: `scripts/run-lidar.sh --mapper-replay lidar/mapper/recordings/<file>.esd`.
3. **Open Room analysis on a real scan.** The classifier has only seen
   simulated rooms. Look at whether walls, floor and furniture come out
   right, and send Ryan a screenshot if not: the thresholds are in
   `src/mapper-adapter.js` (`classifierSteps`) and `src/room-classifier.js`.

## Setup (10 minutes before)

1. iPhone Personal Hotspot over USB to the Mac.
2. `scripts/run-lidar.sh --mapper` in the repo. Do not start the bridge: both
   use port 8765.
3. Phone app: Mac URL `ws://172.20.10.2:8770/depth` (check the Mac's address),
   depth source LiDAR only, Start streaming.
4. Browser: `http://127.0.0.1:4173/`, Sensor feed **Sonar / Preview**, Connect.
   A second tab on `http://127.0.0.1:8780/` for the dense map.
5. Props: a table or chair in open floor, a box, and one corner or doorway you
   will leave unscanned on purpose.

## How to scan so tracking holds

From the real runs in the mapper log:

- Start pointed at a wall 1 to 3 m away, not at a desk or your hand. The map
  will not start on a surface closer than half a meter.
- Sweep slowly. Fast pans into new area are where tracking was lost.
- Overlap: keep part of what you already scanned in view as you turn.
- Do not just spin in place. Take a step or two and revisit earlier areas.
- Do not stop and restart the app mid-scan. A restart can split the map.
- Stay within about 3.5 m of what you are mapping.
- Long blank walls and corridors are the weak case. Keep a corner or
  furniture in view.

## Sequence (about 3 minutes)

| Step | Do | Say | Screen |
|---|---|---|---|
| 1 | Start streaming, sweep the near wall and the table | "Depth from the phone's LiDAR, position from the depth and motion sensors. No camera image is used." | Map fills in; badge reads LiDAR map |
| 2 | Step sideways, keep scanning | "It keeps what it has seen as we move." | Earlier walls stay while new ones appear |
| 3 | Switch to the dense map tab | "This is the full map, a few hundred thousand points." | Dense view |
| 4 | Back to the viewer, click **Room analysis** | "It sorts the map into floor, walls and objects and measures each object. It does not claim to know what they are." | Floor plan with lettered objects and heights |
| 5 | Point at the black area you left unscanned | "Black is not observed. We never call that clear." | Unscanned corner stays black |
| 6 (if the dark test passed) | Lights off, scan a new section | "Same result with the lights off." | Map keeps growing |
| 7 | Download PNG; Save snapshot | "The plan and the scan can be reviewed afterwards." | Saved map |

## If something fails

| Failure | Do |
|---|---|
| Phone cannot reach the Mac | Check hotspot and the Mac address. Otherwise replay the real recording and say it is a replay |
| Map stays empty | Point at a wall 1 to 3 m away and hold for a few seconds |
| Status shows `lost` | Stop moving, point back at something already mapped, wait |
| Map splits or smears | Stop streaming, restart the mapper, rescan slower. Or switch to the replay |
| Viewer shows nothing | Sensor feed must be Sonar / Preview and the address `ws://127.0.0.1:8765/ws` |
| Room analysis looks wrong | Scan walls floor to head height first. Partly scanned walls show up as tall "objects" |

A simulated run (`--mapper-sim`) is a last resort and must be described as
simulated.

## Limits to state out loud

- About 3.5 m useful range. No seeing through walls, smoke or fog.
- Position comes from matching depth frames, so blank walls and fast motion
  can lose it.
- The classifier is geometric rules, not a trained model. It measures objects
  and does not identify them or detect people. Anything taller than 1.2 m,
  such as a person or a door, is labelled wall.
- Not observed is not the same as empty or safe.

## Parked

- Bridge path (`websocket-bridge --lidar`, `ios-lidar/`): fallback only. It
  has a coverage map, scanner path and audio cues, but its app has never been
  compiled.
- Sonar range ingestion (PR #6): no hardware to test with.
- Databricks: works per the mapper log. Mention it only if a sponsor prize
  needs it.
- Change detection between two scans, headgear mockup: not built.
