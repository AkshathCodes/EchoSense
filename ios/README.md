# EchoSense LiDAR (iPhone app)

Replaces the sonar headset as the EchoSense sensor. The app reads the iPhone's
LiDAR depth map, shows it as a false-color picture, reports the distance to the
nearest obstacle ahead with haptic pulses, and streams 3D points to the web
viewer through the bridge.

**Status: written without a Mac. This code has never been compiled or run.**
Expect to fix a few compiler errors on first build. The bridge and viewer side
is tested (`websocket-bridge/tests/test_relay.py`, `test/sonar.test.js`).

## Requirements

- A LiDAR iPhone: 12 Pro, 13 Pro, 14 Pro, 15 Pro, 16 Pro, 17 Pro (or Pro Max).
  Non-Pro iPhones have no LiDAR and the app says so on launch.
- iOS 16 or later, a Mac with Xcode 16 or later, a USB cable.
- A free Apple ID is enough to install on your own phone.

## Build and install

1. Open `ios/EchoSenseLiDAR.xcodeproj`.
2. Select the EchoSenseLiDAR target, **Signing & Capabilities**, pick your
   Team (your Apple ID as a Personal Team). If Xcode says the bundle
   identifier is taken, change it to anything unique.
3. Plug in the phone, choose it as the run destination, press Run.
4. First run: on the phone, enable Developer Mode (Settings, Privacy &
   Security) and trust your developer certificate (Settings, General, VPN &
   Device Management). Allow camera access when asked.

If the project file will not open, either run `brew install xcodegen &&
xcodegen generate` in `ios/`, or create a new iOS App project (SwiftUI) named
EchoSenseLiDAR, delete its two template Swift files, drag in everything from
`ios/EchoSenseLiDAR/`, and add the keys listed in `project.yml` to the
target's Info tab.

## Stream to the laptop viewer

```sh
# terminal 1, repo root
node serve.js
# terminal 2
cd websocket-bridge
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -B -m sonar_bridge --lidar --origin http://127.0.0.1:4173
```

The bridge prints the address to type into the phone. In the app tap
**Laptop**, enter that address, tap **Connect**, and allow local network
access (the first attempt fails while the prompt is up; the app retries every
two seconds). In the browser open `http://127.0.0.1:4173/` and click
**Connect**.

The phone and laptop must reach each other. Campus Wi-Fi usually blocks
device-to-device traffic. Put the laptop on the phone's Personal Hotspot;
the laptop address is then typically `172.20.10.x`.

No phone handy? `python -B fake_phone.py` in `websocket-bridge/` pushes a
synthetic sweep through the same path.

## Modes

- **Live**: what the phone sees now, relative to the phone and leveled with
  gravity. Needs no camera tracking. About 5,500 points, 8 frames a second.
- **Room map**: accumulates points into a 6 cm grid in the ARKit session frame
  and sends up to 15,000 of them twice a second. Needs normal camera tracking.
  The app pauses the map and shows a banner while tracking is limited.

## What works in the dark, and what does not

- The LiDAR is an infrared emitter and sensor, so it measures range with the
  lights off. Live mode, the depth picture and the distance pulses are the
  parts designed for a dark room.
- ARKit tracks the phone's position with the color camera. In a dark room it
  reports "Too dark to track" and Room map cannot build. The Torch button is
  the workaround.
- ARKit's depth map is LiDAR fused with the camera image. How much it degrades
  with no light at all is **not yet measured by us**. Test this first. If the
  laptop view goes nearly empty, turn on "Send low-confidence points".
- Range is about 5 m. Mirrors, glass and very dark matte surfaces return
  little.
- Smoke and fog scatter infrared. This is not a see-through-smoke sensor, and
  the demo should not claim it is.

## Not done

- No object or person detection. `sonar-ml/` classifies simulated sonar
  volumes and has not been pointed at LiDAR points. Frames carry
  `detections: null`.
- No authentication or TLS on the phone link. Use it on a network you control.

## Files

| File | Job |
|---|---|
| `LiDARScanner.swift` | ARKit session, mode logic, send pacing |
| `DepthProjection.swift` | Depth map to points, nearest obstacle, false-color image |
| `VoxelMap.swift` | Room-map accumulation |
| `ScanPoint.swift` | Point type and the JSON the bridge accepts |
| `BridgeClient.swift` | WebSocket to the laptop, auto-reconnect, frame dropping |
| `ProximityFeedback.swift` | Haptic and click pulses |
| `ContentView.swift` | Screen |
