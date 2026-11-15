"""Opt-in synthetic acquisition diversity, not calibrated hardware physics.

A separate RNG stream leaves layout generation and the default simulator intact.
Only existing XYZ/SNR inputs are changed; no class label is used to select gains.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import math
import numpy as np
from .config import SensorConfig
from .sim.scene import Scene
from .sim.shapes import FLOOR_Z, transform


@dataclass(frozen=True)
class AcquisitionDiversity:
    original_fraction: float = 0.5
    height_m: tuple[float, float] = (0.95, 1.65)
    reflectivity_gain: tuple[float, float] = (0.5, 1.5)
    pitch_deg: tuple[float, float] = (-10.0, 20.0)
    max_range_m: tuple[float, float] = (3.5, 6.0)
    keep_probability: tuple[float, float] = (0.65, 1.0)

    def __post_init__(self):
        if not math.isfinite(self.original_fraction) or not 0 <= self.original_fraction <= 1:
            raise ValueError("original_fraction must be in [0, 1]")
        for name in ("height_m", "reflectivity_gain", "pitch_deg", "max_range_m", "keep_probability"):
            lo, hi = getattr(self, name)
            if not all(math.isfinite(v) for v in (lo, hi)) or lo > hi:
                raise ValueError(f"invalid diversity bounds: {name}")
        for name in ("height_m", "reflectivity_gain", "max_range_m", "keep_probability"):
            if getattr(self, name)[0] <= 0:
                raise ValueError(f"positive bounds required: {name}")
        if self.keep_probability[1] > 1 or self.max_range_m[0] <= 0.2:
            raise ValueError("invalid probability/range bounds")

    @classmethod
    def challenge(cls):
        return cls(original_fraction=0, height_m=(0.8, 1.8), reflectivity_gain=(0.4, 1.7),
                   pitch_deg=(-15, 25), max_range_m=(3.0, 5.5), keep_probability=(0.45, 0.75))


def diversify(scene: Scene, sensor: SensorConfig, config: AcquisitionDiversity,
              rng: np.random.Generator):
    """Return new scene/sensor objects and a point-detection probability, without mutating inputs."""
    if rng.random() < config.original_fraction:
        return scene, sensor, 1.0, {"applied": False}
    height = float(rng.uniform(*config.height_m))
    objects, gains = [], []
    for obj in scene.objects:
        gain = float(rng.uniform(*config.reflectivity_gain))
        objects.append(replace(obj, surface=transform(obj.surface, np.eye(3), (0, 0, -height - FLOOR_Z)),
                               reflectivity_override=float(np.clip(obj.reflectivity * gain, 0.05, 1.0))))
        gains.append(gain)
    limit = min(sensor.max_range_m, float(rng.uniform(*config.max_range_m)))
    if limit <= sensor.min_range_m:
        raise ValueError("diversity range must exceed sensor minimum")
    sensor = replace(sensor, tilt_deg=float(rng.uniform(*config.pitch_deg)), max_range_m=limit)
    keep = float(rng.uniform(*config.keep_probability))
    return Scene(objects), sensor, keep, {"applied": True, "sensor_height_m": height,
        "reflectivity_gains": gains, "pitch_deg": sensor.tilt_deg, "max_range_m": limit,
        "keep_probability": keep}


def thin_detections(frame, keep_probability: float, rng: np.random.Generator):
    """Model missed extracted points; keep labels/instance IDs aligned, never invent returns.

    Raw volume is retained. The downstream cluster classifier consumes points,
    not the volume. Missing entire objects contribute to end-to-end diagnostics.
    """
    keep = rng.random(len(frame.points)) < keep_probability
    return replace(frame, points=frame.points[keep],
        point_labels=None if frame.point_labels is None else frame.point_labels[keep],
        point_instances=None if frame.point_instances is None else frame.point_instances[keep])
