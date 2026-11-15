# HC-SR04 sonar on the phone

Owner: Ryan. **Nothing here has been run on hardware yet.** The software side
is tested with simulated readings only.

The HC-SR04 is strapped to the iPhone, pointing the same way as the LiDAR, and
wired to a microcontroller that sends each distance to the Mac over USB. The
mapper compares it with the LiDAR and flags surfaces only the sonar can
detect, such as glass.

## How the sensor works

1. The microcontroller raises **TRIG** for 10 microseconds.
2. The sensor's transmitter (one of the two metal cans) sends eight cycles of
   40 kHz sound, above human hearing.
3. The sensor raises **ECHO** and starts waiting.
4. The sound hits something and part of it bounces back to the receiver (the
   other can). The sensor drops **ECHO**.
5. The time ECHO was high is the round trip. Sound travels 343 m/s at 20 °C,
   so `distance = time x 343 / 2`. One millisecond is 17 cm.

What that means in practice:

| Property | Value | Consequence |
|---|---|---|
| Range | about 2 cm to 4 m | Nearer or farther reads as `timeout` |
| Beam | a cone, roughly 15° wide at its strongest, weaker out to 30° | It reports the nearest thing anywhere in the cone, not a point |
| Rate | one ping every 65 ms, about 15 a second | Much slower than the LiDAR's depth frames |
| Resolution | about 3 mm; accuracy about 1 cm on a flat wall | Good in range, poor sideways |
| Needs | a hard surface roughly facing it | Fabric, foam, and walls at a steep angle send the echo away and read as `timeout` or too far |
| Temperature | speed of sound rises 0.17% per °C | 10 °C off gives a 1.7% range error; ignore for a demo |

It does not care about light, and it reflects from glass and mirrors. That
is what the LiDAR cannot do, and why the two are worth combining.

## Parts

- HC-SR04 module (4 pins: VCC, Trig, Echo, GND)
- Arduino Uno or Nano (5 V board), USB cable to the Mac
- 4 jumper wires, long enough to reach from the phone to the board (30 cm+)
- For a 3.3 V board only: one 1 kΩ and one 2 kΩ resistor

## Wiring: Arduino Uno or Nano (5 V)

| HC-SR04 pin | Arduino pin |
|---|---|
| VCC | 5V |
| Trig | D9 |
| Echo | D10 |
| GND | GND |

That is the whole circuit. No resistors are needed on a 5 V board.

## Wiring: 3.3 V boards (ESP32, Raspberry Pi Pico, most newer boards)

The sensor still needs 5 V power, and its ECHO pin outputs 5 V, which can
damage a 3.3 V input. Drop it with two resistors:

```
HC-SR04 VCC  -> board 5V / VIN / VBUS
HC-SR04 GND  -> board GND
HC-SR04 Trig -> board GPIO (3.3 V is enough to trigger it)
HC-SR04 Echo -> 1 kΩ -> board GPIO
                        |
                       2 kΩ
                        |
                       GND
```

The GPIO sees 5 V x 2/3 = 3.3 V. Change `TRIG_PIN` and `ECHO_PIN` in the
sketch to the GPIO numbers you used. Modules marked HC-SR04P or "3-5.5 V"
can run from 3.3 V directly, with no resistors.

## Upload and check the sensor alone

1. Open `hcsr04.ino` in the Arduino IDE, pick the board and port, Upload.
2. Open Tools, Serial Monitor at **115200 baud**. A new line should appear
   about 15 times a second.
3. Hold a book flat in front of the sensor at a ruler-measured 30 cm. It
   should read `0.300` give or take a centimeter. Try 1 m against a wall.
4. Point it at open space: `timeout`.
5. **Close the Serial Monitor.** Only one program can hold the port.

If every line is `timeout`: Trig and Echo are swapped, or VCC is not on 5 V.
If readings jump around: the surface is soft or angled, or something else is
inside the cone (your hand, the phone's edge, the cable).

## Mounting it on the phone

The comparison only works if the sonar and the LiDAR look at the same thing.

- **Same direction.** The two cans must face exactly where the rear cameras
  face. A few degrees off and they measure different patches of wall.
- **Close to the LiDAR.** The LiDAR is the dark dot in the rear camera
  cluster. Put the sensor within a few centimeters of it: just above the
  phone's top edge, or beside the camera bump.
- **Nothing in front.** Keep the cans clear of the phone body, case lip and
  fingers. Anything inside the cone gives a false near echo.
- **Do not cover the cameras or the LiDAR dot.**
- **Rigid.** If the sensor wobbles, the readings wobble. Use a 3D-printed or
  cardboard bracket, foam tape and a rubber band or zip tie around a phone
  case. Hot glue to a cheap case works.
- **Strain-relieve the cable.** Tape the wires to the case so a tug does not
  move the sensor. Let the microcontroller hang from the USB cable or tape it
  to the back of the case.
- **Cans side by side horizontally** when the phone is held the way you scan.

Measure where the sensor sits relative to the LiDAR dot, looking from behind
the phone toward the scene: how far right, how far down, how far forward, in
meters. Pass that to the mapper as `--sonar-mount RIGHT,DOWN,FORWARD`, for
example `--sonar-mount 0,-0.04,0` for 4 cm above. Left and up are negative.

## Run it with the mapper

Find the port (`ls /dev/cu.usbmodem* /dev/cu.usbserial*` on a Mac), then:

```sh
SONAR_PORT=/dev/cu.usbmodem1101 scripts/run-lidar.sh --mapper
```

or by hand in `lidar/mapper`:

```sh
.venv/bin/pip install pyserial
.venv/bin/python -m lidar_mapper serve --sonar-port /dev/cu.usbmodem1101 \
    --sonar-mount 0,-0.04,0 --record recordings/session1.esd
```

The mapper's status line gains `sonar 1.02 m vs lidar 1.03 m agree`. The
viewer shows the same under the Room analysis button. With `--record`, the
sonar readings are saved next to the recording as `session1.esd.sonar.jsonl`
and come back automatically on replay.

No sensor? `python -m lidar_mapper sim --serve --sonar-sim` runs **simulated**
sonar readings through the same path, labelled as simulated in the viewer.

## Alignment check (do this before trusting it)

1. Stand 1 m from a flat, bare wall, phone square to it. The viewer should
   say **agree**, with the two distances within about 10 cm.
2. Repeat at 2 m.
3. If the sonar reads much nearer at both distances, something is inside its
   cone. If it reads `timeout`, it is not square to the wall.
4. If it agrees at 1 m but not at 2 m, the sensor is tilted. Re-seat it, or
   tell the mapper the tilt with `--sonar-offset-deg RIGHT,DOWN`.

## What the mapper does with it

For each LiDAR depth frame it takes the LiDAR distances inside the sonar's
cone (`--sonar-cone`, default 10° either side of center) and compares the
nearest of them with the latest sonar reading:

| State | Meaning | Typical cause |
|---|---|---|
| `agree` | Same surface | Ordinary wall or furniture |
| `sonar_closer` | Sonar hears something at least 25 cm (or 15%) nearer than the LiDAR sees | Glass, a mirror, a clear plastic sheet. Or something in the cone the LiDAR missed |
| `lidar_no_return` | The LiDAR has almost nothing in the cone, the sonar has an echo | Glass with open space behind, a very dark or shiny surface |
| `sonar_farther` | The LiDAR sees something nearer than the sonar echo | Soft or angled surface that sent no echo back |
| `no_sonar` | No reading in the last 0.35 s, or out of range | Timeout, cable, too far |

When `sonar_closer` or `lidar_no_return` holds for three frames in a row with
steady readings, and the phone's position is being tracked, the mapper marks
a **sonar-only surface**: one point straight ahead of the camera at the sonar
distance. The viewer draws these in magenta, the floor plan shows them as
diamonds, and an audio cue plays if cues are on.

## Limits to say out loud

- The marked point is right in distance and only approximate sideways. At 2 m
  the reflector could be 35 cm to either side.
- A false "LiDAR cannot see" is possible when a thin object (chair leg, cable)
  sits in the cone: the sonar hears it and the LiDAR's nearest-10% rule may
  not. Check with the wall test.
- The sonar adds no detail to the 3D map and does not help the phone track
  its position. It is one distance, 15 times a second.
- Smoke and fog: ultrasound passes where LiDAR scatters, but this has not
  been tested.

## Demo for the judges

Scan a room normally, then point the phone square at a window or glass door
from about a meter. The LiDAR reports the wall or the outdoors beyond it. The
sonar reports the glass. The viewer turns magenta: "surface LiDAR cannot
see". Try it before judging: some coated or dirty glass does return LiDAR.
