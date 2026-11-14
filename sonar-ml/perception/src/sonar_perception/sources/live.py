"""Live sensor driver — STUB until hardware exists.

Not imported by `sources/__init__.py` so nothing depends on it yet.

To implement (with the hardware/firmware team):
  1. Read raw multi-channel frames from the firmware stream
     (format to be documented in docs/interfaces/raw-stream.md).
  2. Matched-filter each channel against the transmitted chirp -> range profiles.
  3. Beamform (delay-and-sum to start) over `SensorConfig.grid()` az/el bins
     using mic positions from docs/interfaces/sensor-geometry.md
     and the speed of sound from the measured temperature.
  4. Apply TVG, then `grid.extract_points(...)` with the configured threshold.
  5. Yield `SonarFrame(meta={"source": "live", ...})` — no labels.

If the team buys a Calyo Pulse instead, this becomes a thin wrapper around its
Python SDK (it already outputs point clouds and 2D intensity).
"""

from __future__ import annotations

from collections.abc import Iterator

from ..config import SensorConfig
from ..frame import SonarFrame
from .base import SensorSource


class LiveSonarSource(SensorSource):
    def __init__(self, port: str, sensor: SensorConfig | None = None) -> None:
        self.port = port
        self.sensor = sensor or SensorConfig()

    def frames(self) -> Iterator[SonarFrame]:
        raise NotImplementedError("Live sonar driver not implemented yet — see module docstring.")
