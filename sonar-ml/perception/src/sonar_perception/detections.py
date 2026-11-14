"""Detections output format (docs/interfaces/detections.md)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from .frame import SonarFrame
from .sim.shapes import CLASSES

DETECTIONS_FORMAT_VERSION = "0.1"


@dataclass
class Detection:
    id: int
    class_id: int
    confidence: float
    probs: dict[str, float]
    centroid: list[float]
    range_m: float
    azimuth_deg: float
    elevation_deg: float
    bbox_min: list[float]
    bbox_max: list[float]
    n_points: int
    mean_intensity: float
    gt_class: str | None = None

    @property
    def class_name(self) -> str:
        return CLASSES[self.class_id]

    def to_dict(self) -> dict:
        d = asdict(self)
        d = {"id": d.pop("id"), "class": self.class_name, **d}
        if d["gt_class"] is None:
            d.pop("gt_class")
        return d

    @classmethod
    def from_cluster(
        cls, det_id: int, points: np.ndarray, probs: np.ndarray, gt_label: int | None = None
    ) -> "Detection":
        xyz = points[:, :3].astype(np.float64)
        c = xyz.mean(axis=0)
        r = float(np.linalg.norm(c))
        k = int(np.argmax(probs))
        return cls(
            id=det_id,
            class_id=k,
            confidence=round(float(probs[k]), 4),
            probs={CLASSES[i]: round(float(p), 4) for i, p in enumerate(probs)},
            centroid=[round(float(v), 3) for v in c],
            range_m=round(r, 3),
            azimuth_deg=round(math.degrees(math.atan2(c[1], c[0])), 2),
            elevation_deg=round(math.degrees(math.asin(np.clip(c[2] / max(r, 1e-9), -1, 1))), 2),
            bbox_min=[round(float(v), 3) for v in xyz.min(axis=0)],
            bbox_max=[round(float(v), 3) for v in xyz.max(axis=0)],
            n_points=int(len(points)),
            mean_intensity=round(float(points[:, 3].mean()), 4),
            gt_class=CLASSES[gt_label] if gt_label is not None and gt_label >= 0 else None,
        )


def frame_detections_dict(frame: SonarFrame, detections: list[Detection], model_name: str) -> dict:
    cond = frame.meta.get("conditions")
    return {
        "format_version": DETECTIONS_FORMAT_VERSION,
        "frame": {
            "timestamp": frame.timestamp,
            "source": frame.meta.get("source"),
            "sensor_id": frame.meta.get("sensor_id"),
            "scene_id": frame.meta.get("scene_id"),
            "conditions": cond.get("name") if isinstance(cond, dict) else cond,
            "n_points": int(len(frame.points)),
        },
        "model": model_name,
        "detections": [d.to_dict() for d in detections],
    }
