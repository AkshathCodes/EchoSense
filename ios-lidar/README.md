# ECHO LiDAR publisher (iPhone app)

Owner: Rishi. Reads the iPhone's LiDAR depth map through ARKit, converts it to
world-space points, and publishes `lidar_frame` v1 messages to the bridge
([protocol](../websocket-bridge/LIDAR_PROTOCOL.md)). It also shows the depth
map on screen with the distance to the nearest obstacle.

**Status: written without a Mac. This code has never been compiled or run.**
Expect to fix a few compiler errors on first build. The message text it builds
is checked against the bridge and viewer by fixtures
(`websocket-bridge/tests/test_lidar.py`, `test/lidar.test.js`), but no real
frame has been captured yet.

## Requirements

- A LiDAR iPhone: 12 Pro, 13 Pro, 14 Pro, 15 Pro, 16 Pro, 17 Pro (or Pro Max).
  Non-Pro iPhones have no LiDAR and the app says so on launch.
- iOS 16 or later, a Mac with Xcode 16 or later, a USB cable.
- A free Apple ID is enough to install on your own phone.

## Build and install

1. Open `ios-lidar/EchoSenseLiDAR.xcodeproj`.
2. Select the EchoSenseLiDAR target, **Signing & Capabilities**, pick your
   Team (your Apple ID as a Personal Team). If Xcode says the bundle
   identifier is taken, change it to anything unique.
3. Plug in the phone, choose it as the run destination, press Run.
4. First run: on the phone, enable Developer Mode (Settings, Privacy &
   Security) and trust your developer certificate (Settings, General, VPN &
   Device Management). Allow camera access when asked.

If the project file will not open, either run `brew install xcodegen &&
xcodegen generate` in `ios-lidar/`, or create a new iOS App project (SwiftUI) named
EchoSenseLiDAR, delete its two template Swift files, drag in everything from
`ios-lidar/EchoSenseLiDAR/`, and add the keys listed in `project.yml` to the
target's Info tab.

## Mac setup for the laptop side

- **Python 3.11 or later.** The `python3` that ships with macOS is 3.9 and
  the bridge will not install on it. Check with `python3 --version`. If it is
  older, `brew install python@3.12` and create the venv with
  `python3.12 -m venv .venv`.
- **Node 20 or later** for `node serve.js`: `brew install node`.
- The first time the bridge starts with `--lidar`, macOS asks whether Python
  may accept incoming network connections. Click **Allow**, or the phone
  cannot reach it.
- If Xcode refuses to open the project as "created by a newer or unsupported
  version", the Xcode is older than 16. Update Xcode or use the `xcodegen`
  fallback above.

## Operate

```sh
# terminal 1, repo root
node serve.js
# terminal 2
cd websocket-bridge
python3 -m venv .venv && .venv/bin/pip install -e .   # needs Python 3.11 or later
.venv/bin/python -B -m sonar_bridge --lidar --record session.jsonl --origin http://127.0.0.1:4173
```

1. The bridge prints the address to type into the phone. In the app tap
   **Laptop**, enter it, tap **Connect**, and allow local network access. The
   first attempt fails while that prompt is up; the app retries every two
   seconds.
2. In the browser open `http://127.0.0.1:4173/` and click **Connect**.
3. On the phone tap **Start scan**. Move slowly. Tap **Stop scan** to stop
   sending. **New** resets ARKit's origin and starts a new session, which the
   viewer shows as a fresh map.

The phone and laptop must reach each other. Campus Wi-Fi usually blocks
device-to-device traffic. Put the laptop on the phone's Personal Hotspot; the
laptop address is then typically `172.20.10.x`.

## What it sends

About 1,000 points a frame (every 7th pixel of the 256 x 192 depth map,
confidence medium or high, 0.1 to 5 m) at about 3 frames a second, with the
camera pose and tracking state. While tracking is not normal it sends the pose
with no points, because world coordinates are not trustworthy then. A new
`session_id` is issued on launch, on **New**, after an interruption, and after
relocalization.

## Checks to run on the real device

None of these have been done.

- Scale: scan a wall from a tape-measured 1 m and 2 m. The readout and the
  viewer should agree with the tape.
- Orientation: the floor should appear flat and below the scanner path in the
  viewer, and walking forward should move the path away from its start.
- Tracking: cover the camera. The status should leave "Tracking" and the
  viewer should stop adding points.
- Record 20 to 30 seconds with `--record` and commit nothing; keep the file
  for the replay backup.

## Limits

- ARKit tracks position with the color camera. In a dark or featureless room
  tracking drops and no points are sent. The Torch button helps.
- Range is about 5 m. Mirrors, glass and very dark matte surfaces return
  little.
- LiDAR does not see through walls, smoke or fog.
- No authentication or TLS on the phone link. Use a network you control.

## Files

| File | Job |
|---|---|
| `LiDARScanner.swift` | ARKit session, session ids, send pacing |
| `DepthProjection.swift` | Depth map to world points, nearest obstacle, false-color image |
| `ScanPoint.swift` | Point type and the `lidar_frame` v1 text |
| `BridgeClient.swift` | WebSocket to the bridge, auto-reconnect, frame dropping |
| `ProximityFeedback.swift` | Haptic and click pulses |
| `ContentView.swift` | Screen |
