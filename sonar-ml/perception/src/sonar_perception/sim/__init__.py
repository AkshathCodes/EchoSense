"""Physics-informed in-air sonar simulator (ADR-0003)."""

from .acoustics import Returns, simulate_returns
from .scene import Scene, random_scene
from .shapes import CLASSES, NOISE, NOISE_CLASS, OBJECT_CLASSES

__all__ = ["CLASSES", "NOISE", "NOISE_CLASS", "OBJECT_CLASSES", "Returns", "Scene", "random_scene", "simulate_returns"]
