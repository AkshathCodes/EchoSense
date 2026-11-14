"""Sonar perception: simulate in-air sonar, build 3D maps, segment, classify.

The hardware-agnostic seam is :class:`sonar_perception.frame.SonarFrame`.
See sonar-ml/docs/interfaces/sonar-frame.md.
"""

from .frame import FORMAT_VERSION, SonarFrame, SphericalGrid

__all__ = ["FORMAT_VERSION", "SonarFrame", "SphericalGrid"]
__version__ = "0.1.0"
