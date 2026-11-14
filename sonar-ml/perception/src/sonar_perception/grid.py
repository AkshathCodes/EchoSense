"""3D mapping: returns -> spherical intensity volume -> point cloud (ADR-0002, ADR-0004)."""

from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter

from .config import EnvironmentConfig, SensorConfig
from .frame import SphericalGrid
from .sim.acoustics import Returns

EMPTY = -2  # label-volume sentinel: no return landed in this voxel


def spherical_to_cartesian(r: np.ndarray, az: np.ndarray, el: np.ndarray) -> np.ndarray:
    ce = np.cos(el)
    return np.stack([r * ce * np.cos(az), r * ce * np.sin(az), r * np.sin(el)], axis=-1)


def cartesian_to_spherical(xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r = np.linalg.norm(xyz, axis=-1)
    az = np.arctan2(xyz[..., 1], xyz[..., 0])
    el = np.arcsin(np.clip(xyz[..., 2] / np.maximum(r, 1e-9), -1, 1))
    return r, az, el


def _bin(values: np.ndarray, edges: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    idx = np.searchsorted(edges, values, side="right") - 1
    valid = (idx >= 0) & (idx < len(edges) - 1)
    return idx, valid


def rasterize(ret: Returns, grid: SphericalGrid) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Accumulate return amplitudes into the grid.

    Returns (volume, label_vol, instance_vol). label/instance volumes hold the
    label of the strongest return per voxel, or EMPTY.
    """
    shape = grid.shape
    volume = np.zeros(shape, np.float64)
    label_vol = np.full(shape, EMPTY, np.int16)
    inst_vol = np.full(shape, EMPTY, np.int32)
    if len(ret) == 0:
        return volume, label_vol, inst_vol
    ri, v1 = _bin(ret.range_m, grid.range_edges)
    ai, v2 = _bin(ret.az, grid.az_edges)
    ei, v3 = _bin(ret.el, grid.el_edges)
    v = v1 & v2 & v3
    if not v.any():
        return volume, label_vol, inst_vol
    lin = np.ravel_multi_index((ri[v], ai[v], ei[v]), shape)
    amp, lab, inst = ret.amplitude[v], ret.label[v], ret.instance[v]
    np.add.at(volume.reshape(-1), lin, amp)
    order = np.argsort(-amp, kind="stable")  # strongest first
    uniq, first = np.unique(lin[order], return_index=True)
    label_vol.reshape(-1)[uniq] = lab[order][first]
    inst_vol.reshape(-1)[uniq] = inst[order][first]
    return volume, label_vol, inst_vol


def apply_sensor_response(
    volume: np.ndarray,
    grid: SphericalGrid,
    sensor: SensorConfig,
    env: EnvironmentConfig,
    rng: np.random.Generator,
) -> np.ndarray:
    """Beam/range blur (in spherical bins), time-varying gain, additive absolute noise."""
    dr = float(np.diff(grid.range_edges).mean())
    da = float(np.diff(grid.az_edges).mean())
    de = float(np.diff(grid.el_edges).mean())
    beam = math.radians(sensor.beam_sigma_deg)
    out = gaussian_filter(volume, sigma=(sensor.range_sigma_m / dr, beam / da, beam / de), mode="constant")
    rc = grid.centers[0]
    out = out * (rc[:, None, None] ** sensor.tvg_exponent)
    noise = sensor.noise_reference * 10 ** (env.noise_level_db / 20)  # absolute, scene-independent
    noise = noise / np.sqrt(max(1, sensor.pings_averaged))  # averaging N pings: noise / sqrt(N)
    out = out + np.abs(rng.normal(0, 1, out.shape)) * noise
    return out.astype(np.float32)


def extract_points(
    volume: np.ndarray,
    grid: SphericalGrid,
    threshold_db: float,
    label_vol: np.ndarray | None = None,
    inst_vol: np.ndarray | None = None,
    max_label_dist_bins: float = 3.0,
    noise_margin_db: float | None = 15.0,
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
    """Threshold the volume into points.

    threshold = max(peak * 10**(threshold_db/20), noise * 10**(noise_margin_db/20))
    where `noise` is the volume median (most voxels are empty, so the median
    estimates the noise floor). This is a crude global CFAR; without it, a
    noisy frame fills with false points (found 2026-11-14, see log §9).

    Voxels lit only by blur spill inherit the label of the nearest voxel that
    received a direct return, if within `max_label_dist_bins`; otherwise NOISE.
    """
    peak = float(volume.max())
    if peak <= 0:
        return np.zeros((0, 4), np.float32), None, None
    thresh = peak * 10 ** (threshold_db / 20)
    if noise_margin_db is not None:
        thresh = max(thresh, float(np.median(volume)) * 10 ** (noise_margin_db / 20))
    mask = volume >= thresh
    idx = np.nonzero(mask)
    rc, ac, ec = grid.centers
    xyz = spherical_to_cartesian(rc[idx[0]], ac[idx[1]], ec[idx[2]])
    # format 0.2: intensity = SNR, i.e. amplitude relative to the frame's estimated noise floor
    # (volume median). Scene-independent like a real CFAR-normalized output. 0.1 used amplitude/peak;
    # a brief absolute-amplitude variant hurt noise rejection (0.94 -> 0.78), see log 2026-11-14 session 3.
    noise_floor = max(float(np.median(volume)), 1e-12)
    intensity = volume[idx] / noise_floor
    points = np.concatenate([xyz, intensity[:, None]], axis=1).astype(np.float32)
    if label_vol is None:
        return points, None, None

    empty = label_vol == EMPTY
    if empty.all():
        n = len(points)
        return points, np.full(n, -1, np.int16), np.full(n, -1, np.int32)
    dist, near = distance_transform_edt(empty, return_indices=True)
    near_idx = tuple(near[k][idx] for k in range(3))
    labels = label_vol[near_idx].astype(np.int16)
    far = dist[idx] > max_label_dist_bins
    labels[far] = -1
    insts = None
    if inst_vol is not None:
        insts = inst_vol[near_idx].astype(np.int32)
        insts[far] = -1
    return points, labels, insts
