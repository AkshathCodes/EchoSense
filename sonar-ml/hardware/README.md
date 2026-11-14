# hardware/

Owned by the hardware sub-team. **Nothing designed yet** (as of 2026-11-14).

## What perception needs from you

Perception is hardware-agnostic, but its simulator and grids are tuned by
config. When the design firms up, fill in
[docs/interfaces/sensor-geometry.md](../docs/interfaces/sensor-geometry.md):

- Transmitter: center frequency, bandwidth, chirp shape, beam width
- Receiver: number of mics, positions (mm, sensor frame), sample rate, mic frequency response
- Field of view (azimuth, elevation), max range, expected range/angle resolution
- Scan method: pan-tilt mechanical sweep vs. static mic array with beamforming
- Frame rate

## Options considered so far

See [docs/research/02-in-air-sonar-and-ml.md](../docs/research/02-in-air-sonar-and-ml.md)
and the log entry [2026-11-13](../docs/log/2026-11-13-ideation-and-research.md):

1. **Pan-tilt scan** — one 40 kHz TX/RX on two servos. Cheapest, slow, wide beam → blurry.
2. **Mic array + beamforming** — one ultrasonic emitter + 4–8+ ultrasonic-capable MEMS mics (PDM), 192 kHz+ sampling, delay-and-sum. The credible version; similar in spirit to eRTIS / nRTIS (Univ. Antwerp).
3. **Buy a 3D ultrasound eval kit** (e.g. Calyo Pulse, outputs point clouds via Python SDK). De-risks hardware entirely; price unknown.

Notes:
- Audio-band arrays (e.g. ReSpeaker) won't work — mics must respond above ~40 kHz. Check datasheets.
- Prefer a **chirp** (e.g. 35–45 kHz sweep) + matched filter over single pings: better range resolution and robustness (cf. UT Austin pulse-compression sonar through flames).
- Include a temperature sensor (thermistor): speed of sound depends on air temperature.

Suggested subfolders once work starts: `bom/`, `cad/`, `schematics/`, `photos/`.
