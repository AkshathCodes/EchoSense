"""Configuration dataclasses.

Every hardware-dependent number lives in `SensorConfig` (placeholders until the
hardware team fills in docs/interfaces/sensor-geometry.md). Physics values in
`EnvironmentConfig` presets are rough guesses — treat them as augmentation
ranges, not ground truth (ADR-0003).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from .frame import SphericalGrid


def speed_of_sound(temp_c: float) -> float:
    """Speed of sound in dry air, m/s (ideal-gas approximation)."""
    return 331.3 * math.sqrt(1.0 + temp_c / 273.15)


@dataclass
class SensorConfig:
    """What the sensor can see and how finely. Placeholder defaults."""

    sensor_id: str = "sim-v0"
    min_range_m: float = 0.2
    max_range_m: float = 6.0
    range_bin_m: float = 0.05
    az_half_fov_deg: float = 60.0
    el_half_fov_deg: float = 30.0
    angle_bin_deg: float = 2.0
    beam_sigma_deg: float = 4.0  # angular blur (array resolution)
    range_sigma_m: float = 0.03  # range blur (chirp bandwidth)
    speed_of_sound_assumed: float = 343.0  # m/s the sensor uses for ToF -> range
    tilt_deg: float = 0.0  # sensor pitched DOWN by this angle; points are reported in the level body frame
    pings_averaged: int = 1  # pings averaged per frame while stationary; noise amplitude falls by sqrt(N)
    tvg_exponent: float = 1.0  # time-varying gain: volume *= range**tvg
    point_threshold_db: float = -50.0  # points = voxels above this, relative to frame peak (dynamic-range limit)
    noise_margin_db: float = 15.0  # ...and at least this far above the noise floor (crude CFAR) -- the main criterion
    # Absolute noise scale (simulation only). Receiver noise does not depend on the scene, so the
    # noise floor is noise_reference * 10**(noise_level_db/20), NOT relative to each frame's peak.
    # 8e-5 = median frame peak of the simulator on 2026-11-14 (see log section 10).
    noise_reference: float = 8e-5

    def grid(self) -> SphericalGrid:
        return SphericalGrid.uniform(
            self.min_range_m,
            self.max_range_m,
            self.range_bin_m,
            math.radians(self.az_half_fov_deg),
            math.radians(self.el_half_fov_deg),
            math.radians(self.angle_bin_deg),
        )


# name: (temperature_c, absorption_db_per_m, turbulence_range_m,
#        turbulence_angle_deg, multipath_rate, noise_level_db)
# 1.3 dB/m is roughly the air absorption at 40 kHz, room temperature.
# Fog/smoke/heat values are GUESSES pending real measurements.
ENV_PRESETS: dict[str, tuple[float, float, float, float, float, float]] = {
    "clear": (20.0, 1.3, 0.000, 0.0, 0.02, -45.0),
    "fog": (25.0, 2.5, 0.010, 0.5, 0.05, -40.0),
    "warm": (60.0, 1.8, 0.020, 1.0, 0.05, -40.0),
    "heavy": (120.0, 4.0, 0.040, 2.0, 0.10, -35.0),
}

# Held-out conditions: NEVER sampled by EnvironmentConfig.random(), so they test
# generalization beyond the training distribution. Values are guesses.
HOLDOUT_PRESETS: dict[str, tuple[float, float, float, float, float, float]] = {
    "extreme": (180.0, 6.0, 0.060, 3.0, 0.15, -32.0),
}


@dataclass
class EnvironmentConfig:
    """Air conditions between sensor and scene."""

    name: str = "clear"
    temperature_c: float = 20.0
    absorption_db_per_m: float = 1.3
    turbulence_range_m: float = 0.0
    turbulence_angle_deg: float = 0.0
    multipath_rate: float = 0.02  # fraction of returns that spawn a ghost
    noise_level_db: float = -45.0  # additive noise floor, relative to SensorConfig.noise_reference

    @property
    def speed_of_sound(self) -> float:
        return speed_of_sound(self.temperature_c)

    @classmethod
    def preset(cls, name: str) -> "EnvironmentConfig":
        presets = {**ENV_PRESETS, **HOLDOUT_PRESETS}
        if name not in presets:
            raise KeyError(f"unknown environment preset {name!r}; choose from {list(presets)}")
        t, a, tr, ta, mp, nl = presets[name]
        return cls(name, t, a, tr, ta, mp, nl)

    @classmethod
    def random(cls, rng: np.random.Generator) -> "EnvironmentConfig":
        """A random preset with mild jitter, for training-time diversity."""
        env = cls.preset(str(rng.choice(list(ENV_PRESETS))))
        return replace(
            env,
            temperature_c=env.temperature_c + rng.normal(0, 5),
            absorption_db_per_m=max(0.5, env.absorption_db_per_m * rng.uniform(0.8, 1.2)),
            multipath_rate=float(np.clip(env.multipath_rate * rng.uniform(0.5, 1.5), 0, 0.3)),
        )


@dataclass
class SimConfig:
    """Scene generation and reflection-model parameters."""

    sample_spacing_m: float = 0.03  # surface sampling density
    specular_exponent: float = 4.0  # cos(theta)**p lobe; larger = more mirror-like
    diffuse_floor: float = 0.03  # minimum scatter at oblique incidence
    edge_bonus: float = 0.6  # extra return from edges/corners
    occlusion_cell_deg: float = 1.0
    min_objects: int = 2
    max_objects: int = 5
    back_wall_prob: float = 0.8
    side_wall_prob: float = 0.3
    floor_prob: float = 1.0  # v1 data was generated without a floor (equivalent to 0.0)
    doorway_in_wall_prob: float = 0.6  # v1 data: 0.0 (free-standing door frames only)
    # relative frequency of object types when filling a scene
    object_weights: tuple[float, float, float, float] = (0.15, 0.35, 0.2, 0.3)  # doorway, furniture, debris, person


@dataclass
class SweepConfig:
    """Multi-view fusion: the wearer sweeps the sensor side to side (and optionally steps forward).

    Frames from each pose are simulated with independent noise and fused into one
    point cloud in the level body frame of the MIDDLE pose (poses assumed known,
    e.g. from an IMU; pose error is not modeled yet). ADR-0013.
    """

    n_poses: int = 1
    yaw_span_deg: float = 0.0  # total yaw sweep, centered on the reference pose
    step_m: float = 0.0  # total forward travel across the sweep (0 = standing still)
    fuse_voxel_m: float = 0.05  # fused points are voxel-downsampled at this size
    min_views: int = 1  # keep a fused voxel only if at least this many poses saw it (rejects one-off noise/ghosts)

    @property
    def enabled(self) -> bool:
        return self.n_poses > 1
