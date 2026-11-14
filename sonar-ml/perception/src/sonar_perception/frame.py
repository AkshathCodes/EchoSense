"""The `SonarFrame` contract (docs/interfaces/sonar-frame.md), in code.

Coordinate frame: origin at the sensor, x forward, y left, z up.
Azimuth = atan2(y, x) (positive left), elevation = asin(z / r) (positive up).
All angles in radians, distances in meters.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

FORMAT_VERSION = "0.2"


@dataclass
class SphericalGrid:
    """Bin edges of the (range, azimuth, elevation) intensity volume."""

    range_edges: np.ndarray
    az_edges: np.ndarray
    el_edges: np.ndarray

    @property
    def shape(self) -> tuple[int, int, int]:
        return (len(self.range_edges) - 1, len(self.az_edges) - 1, len(self.el_edges) - 1)

    @staticmethod
    def _centers(edges: np.ndarray) -> np.ndarray:
        return 0.5 * (edges[:-1] + edges[1:])

    @property
    def centers(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return (
            self._centers(self.range_edges),
            self._centers(self.az_edges),
            self._centers(self.el_edges),
        )

    @classmethod
    def uniform(
        cls,
        min_range: float,
        max_range: float,
        range_bin: float,
        az_half: float,
        el_half: float,
        angle_bin: float,
    ) -> "SphericalGrid":
        def edges(lo: float, hi: float, step: float) -> np.ndarray:
            n = max(1, int(round((hi - lo) / step)))
            return np.linspace(lo, lo + n * step, n + 1)

        return cls(
            range_edges=edges(min_range, max_range, range_bin),
            az_edges=edges(-az_half, az_half, angle_bin),
            el_edges=edges(-el_half, el_half, angle_bin),
        )


@dataclass
class SonarFrame:
    """One sonar capture: intensity volume + point cloud + metadata (+ optional labels)."""

    timestamp: float
    grid: SphericalGrid
    volume: np.ndarray  # float32 [R, A, E]
    points: np.ndarray  # float32 [N, 4]: x, y, z (level body frame), intensity (SNR: amplitude / frame noise floor)
    meta: dict = field(default_factory=dict)
    point_labels: np.ndarray | None = None  # int16 [N], -1 = noise
    point_instances: np.ndarray | None = None  # int32 [N], -1 = noise

    def __post_init__(self) -> None:
        if self.volume.shape != self.grid.shape:
            raise ValueError(f"volume shape {self.volume.shape} != grid shape {self.grid.shape}")
        if self.points.ndim != 2 or self.points.shape[1] != 4:
            raise ValueError(f"points must be [N, 4], got {self.points.shape}")
        n = len(self.points)
        for name in ("point_labels", "point_instances"):
            arr = getattr(self, name)
            if arr is not None and len(arr) != n:
                raise ValueError(f"{name} length {len(arr)} != number of points {n}")
        self.meta.setdefault("format_version", FORMAT_VERSION)

    @property
    def has_labels(self) -> bool:
        return self.point_labels is not None

    def save(self, path: str | Path) -> None:
        arrays = dict(
            volume=self.volume.astype(np.float32),
            points=self.points.astype(np.float32),
            range_edges=self.grid.range_edges,
            az_edges=self.grid.az_edges,
            el_edges=self.grid.el_edges,
            timestamp=np.array(self.timestamp),
            meta=np.array(json.dumps(self.meta)),
        )
        if self.point_labels is not None:
            arrays["point_labels"] = self.point_labels.astype(np.int16)
        if self.point_instances is not None:
            arrays["point_instances"] = self.point_instances.astype(np.int32)
        np.savez_compressed(path, **arrays)

    @classmethod
    def load(cls, path: str | Path) -> "SonarFrame":
        with np.load(path, allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            version = str(meta.get("format_version", "0"))
            if version.split(".")[0] != FORMAT_VERSION.split(".")[0]:
                raise ValueError(f"unsupported SonarFrame format_version {version}")
            return cls(
                timestamp=float(z["timestamp"]),
                grid=SphericalGrid(z["range_edges"], z["az_edges"], z["el_edges"]),
                volume=z["volume"],
                points=z["points"],
                meta=meta,
                point_labels=z["point_labels"] if "point_labels" in z else None,
                point_instances=z["point_instances"] if "point_instances" in z else None,
            )
