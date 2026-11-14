from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from ..frame import SonarFrame


class SensorSource(ABC):
    """Anything that yields `SonarFrame`s: simulator, recordings, live hardware."""

    @abstractmethod
    def frames(self) -> Iterator[SonarFrame]:
        """Yield frames until exhausted (finite sources) or forever (live)."""

    def __iter__(self) -> Iterator[SonarFrame]:
        return self.frames()

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release hardware / files. Default: nothing."""
