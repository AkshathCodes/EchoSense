from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ..frame import SonarFrame
from .base import SensorSource


class RecordedSource(SensorSource):
    """Replay a folder of saved `SonarFrame` .npz files in filename order."""

    def __init__(self, folder: str | Path, pattern: str = "*.npz") -> None:
        self.paths = sorted(Path(folder).glob(pattern))
        if not self.paths:
            raise FileNotFoundError(f"no frames matching {pattern} in {folder}")

    def __len__(self) -> int:
        return len(self.paths)

    def frames(self) -> Iterator[SonarFrame]:
        for p in self.paths:
            yield SonarFrame.load(p)
