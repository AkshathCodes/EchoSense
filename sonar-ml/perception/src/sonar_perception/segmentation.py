"""Scene -> object candidates via DBSCAN (ADR-0005, ADR-0012).

Default mode clusters in the sensor's native spherical coordinates:
(range, az * ang_scale, el * ang_scale), so the neighborhood radius is roughly
one resolution cell everywhere instead of a fixed number of meters. With xyz
DBSCAN at eps 0.25 m, 23% of visible people merged into neighbors; spherical
eps 0.12 / ang_scale 2 (~3.4 deg, about one beam width) cut that to 13% with
no extra fragmentation (log 2026-11-14 session 3).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.cluster import DBSCAN

from .frame import SonarFrame
from .sim.shapes import NOISE, NOISE_CLASS


@dataclass
class Cluster:
    points: np.ndarray  # [k, 4] x, y, z, intensity
    label: int  # majority ground-truth class; NOISE_CLASS if noise-dominated; -1 if unlabeled
    purity: float  # fraction of points carrying the majority label (nan if unlabeled)
    instance: int  # majority instance id, -1 if unknown


DEFAULT_MODE = "spherical"
DEFAULT_EPS = {"spherical": 0.12, "xyz": 0.25}
DEFAULT_ANG_SCALE = 2.0


def cluster_points(
    points: np.ndarray,
    eps: float | None = None,
    min_samples: int = 4,
    mode: str = DEFAULT_MODE,
    ang_scale: float = DEFAULT_ANG_SCALE,
) -> np.ndarray:
    """Cluster ids per point; -1 = DBSCAN noise. mode: 'spherical' (default) or 'xyz'."""
    if len(points) == 0:
        return np.zeros(0, np.int32)
    eps = DEFAULT_EPS[mode] if eps is None else eps
    if mode == "spherical":
        xyz = points[:, :3].astype(np.float64)
        r = np.linalg.norm(xyz, axis=1)
        az = np.arctan2(xyz[:, 1], xyz[:, 0])
        el = np.arcsin(np.clip(xyz[:, 2] / np.maximum(r, 1e-9), -1, 1))
        feats = np.stack([r, az * ang_scale, el * ang_scale], axis=1)
    elif mode == "xyz":
        feats = points[:, :3]
    else:
        raise ValueError(f"unknown clustering mode {mode!r}")
    return DBSCAN(eps=eps, min_samples=min_samples).fit_predict(feats).astype(np.int32)


def _majority(values: np.ndarray) -> tuple[int, float]:
    vals, counts = np.unique(values, return_counts=True)
    i = int(np.argmax(counts))
    return int(vals[i]), float(counts[i] / counts.sum())


def extract_clusters(
    frame: SonarFrame,
    eps: float | None = None,
    min_samples: int = 4,
    min_points: int = 8,
    mode: str = DEFAULT_MODE,
) -> tuple[list[Cluster], np.ndarray]:
    """Returns (clusters, per-point cluster ids)."""
    ids = cluster_points(frame.points, eps, min_samples, mode=mode)
    clusters: list[Cluster] = []
    for cid in np.unique(ids):
        if cid < 0:
            continue
        m = ids == cid
        if m.sum() < min_points:
            continue
        if frame.point_labels is not None:
            label, purity = _majority(frame.point_labels[m])
            if label == NOISE:
                label = NOISE_CLASS
        else:
            label, purity = -1, float("nan")
        inst = _majority(frame.point_instances[m])[0] if frame.point_instances is not None else -1
        clusters.append(Cluster(frame.points[m], label, purity, inst))
    return clusters, ids
