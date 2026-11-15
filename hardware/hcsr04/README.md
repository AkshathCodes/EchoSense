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
- ESP32 dev board (what the team has) or an Arduino Uno or Nano, with a USB
  **data** cable to the Mac. Many micro-USB cables are charge-only.
- Breadboard and jumper wires
- 4 wires, 40 to 50 cm, from the sensor on the phone to the board
- For the ESP32: one 1 kΩ and one 2 kΩ resistor (or the substitutes below)

## Seeed Studio XIAO build, soldered, no breadboard

This assumes a **Seeed Studio XIAO** (ESP32C3, ESP32S3, RP2040, SAMD21 or
nRF52840). All of them use 3.3 V pins, so the Echo divider is still needed.
A 5 V Seeeduino wires like the Arduino table further down instead.

The XIAO pads used, as printed on the board or its pinout card:

| HC-SR04 | XIAO pad | Notes |
|---|---|---|
| VCC | **5V** (also labelled VBUS or VUSB) | 5 V from the USB cable. Not the 3V3 pad |
| GND | **GND** | |
| Trig | **D1** | Direct wire |
| Echo | **D2**, through the divider | Never direct |

What to solder:

1. **Four wires onto the HC-SR04 pins**, 40 to 50 cm, four colors. Cover each
   joint with heat-shrink or tape.
2. **VCC wire to the XIAO 5V pad. Trig wire to D1.**
3. **The divider, in line on the Echo wire.** Solder the Echo wire to one leg
   of the 1 kΩ resistor. Twist the other leg of the 1 kΩ together with one
   leg of the 2 kΩ and a short wire, and solder that three-way joint. The
   short wire goes to **D2**. The free leg of the 2 kΩ goes to **GND**.
4. **GND.** The sensor's GND wire and the 2 kΩ leg both go to the XIAO GND
   pad. Twist them together first and solder one joint.
5. Slide heat-shrink over the resistors, or wrap them in tape, so bare legs
   cannot touch each other or the XIAO.

Tips for a board this small: tin the pad and the wire separately, then touch
them together with the iron for a second. Use thin wire. Do not bridge 5V to
GND, which sit near each other on the XIAO: that shorts the USB port. If you
have header pins and female jumpers, solder headers to the XIAO instead and
push the wires on; it is easier to fix.

No 1 kΩ and 2 kΩ? See the substitutes in the ESP32 section below.

Flash it: in the Arduino IDE add Seeed's board package for your XIAO model,
select the board and port, open `hcsr04.ino`, Upload. If the port does not
appear, hold the tiny **B** (boot) button while plugging in USB. Open the
Serial Monitor at 115200. The first line names the pins the sketch chose,
for example `# hcsr04 trig pin 3 echo pin 4` (the numbers are the chip's own
pin numbers for D1 and D2). If every reading is `timeout`, uncomment
`#define SEEED_XIAO` at the top of the sketch and upload again. On a Mac the
XIAO shows up as `/dev/cu.usbmodemXXXX`.

## ESP32 dev board build, step by step

The sketch uses **GPIO 26 for Trig and GPIO 27 for Echo** on an ESP32. Those
are free on the classic 30- and 38-pin DevKit boards. On an S3, C3 or other
variant pick any two free GPIOs and change the numbers at the top of the
sketch.

### 1. Breadboard first, no soldering

1. Push the ESP32 into the breadboard across the center gap. If the board is
   so wide that it covers every hole on one side, use two breadboards side by
   side or female-to-male jumpers straight onto its pins.
2. Sensor **VCC** to the ESP32 pin marked **5V** or **VIN** (USB power). Not
   3V3: most HC-SR04 modules misread or stay silent on 3.3 V.
3. Sensor **GND** to an ESP32 **GND**.
4. Sensor **Trig** to **GPIO 26**. No resistor: the ESP32's 3.3 V is enough
   to trigger the sensor.
5. Sensor **Echo** to an empty breadboard row. From that row, a **1 kΩ**
   resistor to a second empty row. From the second row, a wire to **GPIO 27**
   and a **2 kΩ** resistor to **GND**. GPIO 27 now sees 3.3 V instead of 5 V.

No 1 kΩ and 2 kΩ? Any pair where the resistor to GND is about twice the other
works: 2.2 kΩ and 4.7 kΩ, 10 kΩ and 20 kΩ, or three equal resistors (one from
Echo, two in series to GND). Check with a multimeter if you have one: with
the sensor powered, the GPIO 27 row should never read above 3.3 V.

Do not connect Echo straight to an ESP32 pin. It may work for a while and
then damage the pin.

### 2. Flash and test

1. Arduino IDE: Boards Manager, install **esp32 by Espressif**. Select
   "ESP32 Dev Module" and the board's port.
2. Open `hcsr04.ino`, Upload. If it sits at "Connecting....", hold the
   board's **BOOT** button until the upload starts.
3. Serial Monitor at **115200**. A few lines of boot text, then a distance
   about 15 times a second. Do the 30 cm book test below.
4. Port not listed on the Mac? The board's USB chip needs a driver: CP210x
   (Silicon Labs) or CH340, whichever chip is printed near the USB socket.
   Or the cable is charge-only.

### 3. Solder only what has to survive being carried around

Breadboard contacts are fine on a table and unreliable on a moving phone.
Once the breadboard version reads correctly:

| Solder this | Why |
|---|---|
| Header pins onto the ESP32, if it came without them | Otherwise it cannot sit in the breadboard at all |
| Four 40 to 50 cm wires onto the HC-SR04's four pins, each joint covered with heat-shrink or tape | The sensor rides on the phone; push-on jumpers work loose |
| Optional: the two divider resistors onto a small piece of perfboard, or in line on the Echo wire with heat-shrink over them | Removes the last breadboard joint in the signal path |

Use four wire colors and write down which is which. Keep the ESP32 and
breadboard on the table or in a pocket, and run only the four wires to the
phone. Leave enough slack to sweep the phone around the room.

Before powering a soldered joint, look for bridges between neighbouring
pins. VCC touching GND shorts the USB port.

## Wiring: Arduino Uno or Nano (5 V)

| HC-SR04 pin | Arduino pin |
|---|---|
| VCC | 5V |
| Trig | D9 |
| Echo | D10 |
| GND | GND |

That is the whole circuit. No resistors are needed on a 5 V board.

## Wiring summary: ESP32 and other 3.3 V boards

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

The GPIO sees 5 V x 2/3 = 3.3 V. On an ESP32 the sketch already uses GPIO 26
(Trig) and 27 (Echo). On another board, change `TRIG_PIN` and `ECHO_PIN`. Modules marked HC-SR04P or "3-5.5 V"
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

Find the port on a Mac with `ls /dev/cu.*`. An ESP32 shows up as
`/dev/cu.usbserial-XXXX`, `/dev/cu.SLAB_USBtoUART` or `/dev/cu.wchusbserial-XXXX`;
an Arduino as `/dev/cu.usbmodemXXXX`. Then:

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
