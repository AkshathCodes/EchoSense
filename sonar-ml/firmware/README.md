# firmware/

Owned by the hardware/embedded sub-team. **Nothing written yet** (as of 2026-11-14).

## Expected responsibilities

- Generate the transmit chirp and trigger capture
- Capture synchronized multi-channel mic data (likely PDM → PCM at ≥192 kHz)
- Stream raw frames to a host (laptop / Raspberry Pi) over USB serial or UDP
- Report temperature (thermistor) with each frame
- **Average 4 pings per frame** (or stream all 4 and let the host average). Simulation
  showed this is the cheapest big win for detecting people lying on the floor
  (ADR-0013)
- If an IMU is fitted: timestamped orientation with each frame (for sweep fusion)

Candidate MCUs discussed: Teensy 4.x or STM32 (ESP32 is marginal at these sample rates).

## Hand-off to perception

The host-side driver (in `perception/src/sonar_perception/sources/live.py`) turns
the raw stream into a `SonarFrame`. Agree on the wire format with perception
and document it in `docs/interfaces/raw-stream.md` (create it when ready).
