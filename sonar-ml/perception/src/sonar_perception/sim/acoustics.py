"""Acoustic return model (ADR-0003).

Turns labeled surface samples into a list of echo returns
(measured range, azimuth, elevation, amplitude, label, instance).

Model, per surface sample at true range r with unit normal n:
  1. visible if in FOV/range, front-facing, and not occluded (angular z-buffer)
  2. specular weight  = max(cos(theta)**p, diffuse_floor) + edge_bonus * is_edge
  3. amplitude        = reflectivity * weight * dOmega * spreading * absorption
       dOmega     = spacing**2 * cos(theta) / r**2  (solid angle of the sample;
                    makes voxel sums roughly independent of sampling density)
       spreading  = 1 / r                           (mirror-like extended target)
       absorption = 10 ** (-alpha_dB_per_m * 2r / 20)
  4. measured range   = r * c_assumed / c_true(T)
       warm air -> faster sound -> earlier echo -> object reads CLOSER
       (see docs/log/2026-11-13-ideation-and-research.md, CORRECTION)
  5. turbulence jitter in range and angle
  6. multipath ghosts: weak returns behind real ones, labeled NOISE

All constants are rough; they are augmentation knobs until validated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..config import EnvironmentConfig, SensorConfig, SimConfig
from .scene import Scene
from .shapes import NOISE


@dataclass
class Returns:
    range_m: np.ndarray
    az: np.ndarray
    el: np.ndarray
    amplitude: np.ndarray
    label: np.ndarray  # int16
    instance: np.ndarray  # int32

    def __len__(self) -> int:
        return len(self.range_m)

    @classmethod
    def empty(cls) -> "Returns":
        f = np.zeros(0)
        return cls(f, f, f, f, np.zeros(0, np.int16), np.zeros(0, np.int32))


def _flatten(scene: Scene):
    if not scene.objects:
        return None
    pts = np.concatenate([o.surface.points for o in scene.objects])
    nrm = np.concatenate([o.surface.normals for o in scene.objects])
    edge = np.concatenate([o.surface.is_edge for o in scene.objects])
    lab = np.concatenate([np.full(len(o.surface), o.label, np.int16) for o in scene.objects])
    inst = np.concatenate([np.full(len(o.surface), i, np.int32) for i, o in enumerate(scene.objects)])
    refl = np.concatenate([np.full(len(o.surface), o.reflectivity) for o in scene.objects])
    return pts, nrm, edge, lab, inst, refl


def simulate_returns(
    scene: Scene,
    sensor: SensorConfig,
    env: EnvironmentConfig,
    sim: SimConfig,
    rng: np.random.Generator,
) -> Returns:
    flat = _flatten(scene)
    if flat is None:
        return Returns.empty()
    pts, nrm, edge, lab, inst, refl = flat

    r = np.linalg.norm(pts, axis=1)
    ok = r > 1e-6
    u = np.zeros_like(pts)
    u[ok] = pts[ok] / r[ok, None]
    az = np.arctan2(pts[:, 1], pts[:, 0])
    el = np.arcsin(np.clip(u[:, 2], -1, 1))
    cos_inc = -np.einsum("ij,ij->i", nrm, u)

    az_half = math.radians(sensor.az_half_fov_deg)
    el_half = math.radians(sensor.el_half_fov_deg)
    keep = ok & (r >= sensor.min_range_m) & (r <= sensor.max_range_m)
    keep &= (np.abs(az) <= az_half) & (np.abs(el) <= el_half) & (cos_inc > 0)
    if not keep.any():
        return Returns.empty()
    r, az, el, cos_inc = r[keep], az[keep], el[keep], cos_inc[keep]
    edge, lab, inst, refl = edge[keep], lab[keep], inst[keep], refl[keep]

    # occlusion: per fine angular cell, keep only samples near the nearest range
    cell = math.radians(sim.occlusion_cell_deg)
    n_el = int(math.ceil(2 * el_half / cell)) + 1
    key = np.floor((az + az_half) / cell).astype(np.int64) * n_el + np.floor((el + el_half) / cell).astype(np.int64)
    nearest = np.full(key.max() + 1, np.inf)
    np.minimum.at(nearest, key, r)
    vis = r <= nearest[key] + 2.5 * sim.sample_spacing_m + 0.02
    r, az, el, cos_inc = r[vis], az[vis], el[vis], cos_inc[vis]
    edge, lab, inst, refl = edge[vis], lab[vis], inst[vis], refl[vis]

    weight = np.maximum(cos_inc**sim.specular_exponent, sim.diffuse_floor) + sim.edge_bonus * edge
    d_omega = sim.sample_spacing_m**2 * cos_inc / r**2
    loss = 10 ** (-env.absorption_db_per_m * 2 * r / 20) / r
    amp = refl * weight * d_omega * loss

    r_meas = r * sensor.speed_of_sound_assumed / env.speed_of_sound
    if env.turbulence_range_m > 0:
        r_meas = r_meas + rng.normal(0, env.turbulence_range_m, len(r_meas))
    if env.turbulence_angle_deg > 0:
        s = math.radians(env.turbulence_angle_deg)
        az = az + rng.normal(0, s, len(az))
        el = el + rng.normal(0, s, len(el))

    out = Returns(r_meas, az, el, amp, lab.astype(np.int16), inst.astype(np.int32))
    if env.multipath_rate > 0 and len(out):
        out = _add_ghosts(out, env.multipath_rate, rng)
    return out


def _add_ghosts(ret: Returns, rate: float, rng: np.random.Generator) -> Returns:
    n = rng.binomial(len(ret), rate)
    if n == 0:
        return ret
    src = rng.choice(len(ret), n, replace=True)
    jitter = math.radians(3.0)
    return Returns(
        np.concatenate([ret.range_m, ret.range_m[src] + rng.uniform(0.3, 2.0, n)]),
        np.concatenate([ret.az, ret.az[src] + rng.normal(0, jitter, n)]),
        np.concatenate([ret.el, ret.el[src] + rng.normal(0, jitter, n)]),
        np.concatenate([ret.amplitude, ret.amplitude[src] * rng.uniform(0.05, 0.2, n)]),
        np.concatenate([ret.label, np.full(n, NOISE, np.int16)]),
        np.concatenate([ret.instance, np.full(n, -1, np.int32)]),
    )
