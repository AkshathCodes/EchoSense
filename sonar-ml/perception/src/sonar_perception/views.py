"""Fixed-size model inputs from a cluster's points (numpy; used by torch models).

All views center x/y on the cluster centroid but keep absolute z, for the
reason given in features.py.
"""

from __future__ import annotations

import numpy as np

Z_RANGE = (-1.5, 1.2)  # sensor-frame z covered by views (floor ~ -1.3)
XY_HALF = 1.25  # +/- meters around the centroid


def resample(points: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    k = len(points)
    idx = rng.choice(k, n, replace=k < n)
    return points[idx]


def pointset(points: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """[n, 5]: dx, dy, dz (centered), z_abs, intensity (scaled to max 1)."""
    p = resample(points, n, rng).astype(np.float32)
    c = p[:, :3].mean(axis=0)
    inten = p[:, 3] / max(float(p[:, 3].max()), 1e-6)
    return np.concatenate([p[:, :3] - c, p[:, 2:3], inten[:, None]], axis=1)


def _bin2(a: np.ndarray, lo: float, hi: float, size: int) -> np.ndarray:
    return np.clip(((a - lo) / (hi - lo) * size).astype(int), 0, size - 1)


def bev(points: np.ndarray, size: int = 32) -> np.ndarray:
    """[4, size, size]: top view (occupancy, max intensity) + front view (occupancy, max intensity)."""
    xyz, inten = points[:, :3], points[:, 3] / max(float(points[:, 3].max()), 1e-6)
    c = xyz[:, :2].mean(axis=0)
    xi = _bin2(xyz[:, 0] - c[0], -XY_HALF, XY_HALF, size)
    yi = _bin2(xyz[:, 1] - c[1], -XY_HALF, XY_HALF, size)
    zi = _bin2(xyz[:, 2], *Z_RANGE, size)
    out = np.zeros((4, size, size), np.float32)
    out[0, xi, yi] = 1.0
    np.maximum.at(out[1], (xi, yi), inten)
    out[2, zi, yi] = 1.0
    np.maximum.at(out[3], (zi, yi), inten)
    return out


def voxels(points: np.ndarray, size: int = 16) -> np.ndarray:
    """[2, size, size, size]: occupancy, max intensity."""
    xyz, inten = points[:, :3], points[:, 3] / max(float(points[:, 3].max()), 1e-6)
    c = xyz[:, :2].mean(axis=0)
    xi = _bin2(xyz[:, 0] - c[0], -XY_HALF, XY_HALF, size)
    yi = _bin2(xyz[:, 1] - c[1], -XY_HALF, XY_HALF, size)
    zi = _bin2(xyz[:, 2], *Z_RANGE, size)
    out = np.zeros((2, size, size, size), np.float32)
    out[0, xi, yi, zi] = 1.0
    np.maximum.at(out[1], (xi, yi, zi), inten)
    return out
