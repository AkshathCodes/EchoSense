"""Hand-crafted cluster features for the random-forest classifier (ADR-0007, ADR-0011, ADR-0012).

Absolute height (z in the level body frame) is used on purpose: the sensor is
assumed to be worn at roughly chest height, so z carries real information
(a person's head is high; debris is low). If the mounting changes, revisit.

Intensity features use SNR (amplitude / frame noise floor; SonarFrame format 0.2), logged.
Caveat: material reflectivity in the simulator is a guess (person 0.5,
furniture 0.7, debris 0.9), so intensity features may not transfer to real data
as well as shape features. Check feature importance after real captures.

v2 features (2026-11-14, session 3) target the person confusions found by
`diagnose`: crouching -> furniture, lying -> debris.
"""

from __future__ import annotations

import numpy as np

FEATURE_NAMES = [
    # v1: size and shape
    "log_n_points",
    "extent_x", "extent_y", "extent_z",
    "extent_horiz", "vert_to_horiz",
    "linearity", "planarity", "sphericity",
    "normal_z",
    "centroid_range", "centroid_z", "z_min", "z_max",
    # intensity (SNR, log10)
    "log_int_mean", "log_int_max", "int_cv",
    # v2: vertical width profile: horizontal spread in bottom / middle / top thirds, relative to the widest
    "width_bottom_rel", "width_mid_rel", "width_top_rel",
    "width_top_abs",  # head-sized top (~0.2-0.3 m) vs table/cabinet top (~0.6+ m)
    "frac_points_top", "frac_points_bottom",
    "log_density",  # points per m^2 of bounding footprint+height surface
    "int_z_corr",  # does intensity rise or fall with height?
    "main_axis_horiz",  # 1 = main axis horizontal (lying person, sofa), 0 = vertical (standing person)
]


def _horiz_spread(xy: np.ndarray) -> float:
    if len(xy) < 3:
        return 0.0
    c = xy - xy.mean(axis=0)
    return float(2.0 * np.sqrt(np.linalg.eigvalsh(np.cov(c.T) + 1e-9 * np.eye(2))[-1]))


def cluster_features(points: np.ndarray) -> np.ndarray:
    xyz, inten = points[:, :3].astype(np.float64), np.maximum(points[:, 3].astype(np.float64), 1e-12)
    c = xyz.mean(axis=0)
    ext = xyz.max(axis=0) - xyz.min(axis=0)
    horiz = float(np.hypot(ext[0], ext[1]))
    if len(xyz) >= 3:
        evals, evecs = np.linalg.eigh(np.cov((xyz - c).T) + 1e-9 * np.eye(3))
        l3, l2, l1 = np.maximum(evals, 1e-12)  # ascending -> l1 largest
        normal_z = abs(float(evecs[2, 0]))  # z-component of smallest-variance axis
        main_axis_horiz = 1.0 - abs(float(evecs[2, 2]))  # largest-variance axis
    else:
        l1 = l2 = l3 = 1e-12
        normal_z, main_axis_horiz = 0.0, 0.0
    rng_c = float(np.linalg.norm(c))

    z = xyz[:, 2]
    z0, z1 = z.min(), z.max()
    h = max(z1 - z0, 1e-3)
    bands = [(z <= z0 + h / 3), (z > z0 + h / 3) & (z <= z0 + 2 * h / 3), (z > z0 + 2 * h / 3)]
    widths = [_horiz_spread(xyz[b, :2]) for b in bands]
    wmax = max(max(widths), 1e-3)
    n = len(xyz)
    surface = 2 * (ext[0] * ext[1] + ext[0] * ext[2] + ext[1] * ext[2]) + 1e-3
    int_z_corr = float(np.corrcoef(z, inten)[0, 1]) if n >= 3 and z.std() > 1e-6 and inten.std() > 0 else 0.0

    return np.array(
        [
            np.log(n),
            ext[0], ext[1], ext[2],
            horiz, ext[2] / (horiz + 1e-3),
            (l1 - l2) / l1, (l2 - l3) / l1, l3 / l1,
            normal_z,
            rng_c, c[2], z0, z1,
            np.log10(inten.mean()), np.log10(inten.max()), inten.std() / inten.mean(),
            widths[0] / wmax, widths[1] / wmax, widths[2] / wmax,
            widths[2],
            bands[2].mean(), bands[0].mean(),
            np.log10(n / surface),
            int_z_corr,
            main_axis_horiz,
        ],
        dtype=np.float32,
    )
