"""Synthetic dataset generation and loading. Splits are BY SCENE (never by cluster)."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path

import numpy as np

from . import __version__
from .config import EnvironmentConfig, SensorConfig, SimConfig, SweepConfig
from .features import FEATURE_NAMES, cluster_features
from .segmentation import extract_clusters
from .sim import CLASSES, random_scene
from .sources.synthetic import simulate_sweep
from .views import resample


def generate(
    out_dir: str | Path,
    n_scenes: int,
    seed: int = 0,
    env_mode: str = "random",
    n_points: int = 256,
    save_frames: bool = True,
    sensor: SensorConfig | None = None,
    sim: SimConfig | None = None,
    eps: float | None = None,
    min_samples: int = 4,
    seg_mode: str = "spherical",
    threshold_jitter: bool = True,
    sweep: SweepConfig | None = None,
) -> dict:
    """Simulate `n_scenes` frames, cluster them, and write a cluster dataset.

    threshold_jitter: per scene, draw the detection thresholds from a range
    (point_threshold_db ~ U(-55, -45), noise_margin_db ~ U(10, 18)) so the
    dataset contains realistic numbers of noise clusters (ADR-0009) and the
    classifier doesn't overfit one threshold setting.

    Writes:
      out_dir/scenes/scene_XXXXX.npz  (SonarFrame with labels), if save_frames
      out_dir/clusters.npz            points [M, n_points, 4], features, labels, scene_ids, purity, env
      out_dir/manifest.json
    """
    sensor, sim, sweep = sensor or SensorConfig(), sim or SimConfig(), sweep or SweepConfig()
    out = Path(out_dir)
    (out / "scenes").mkdir(parents=True, exist_ok=True)
    pts, feats, labels, scene_ids, purity, envs = [], [], [], [], [], []
    for i in range(n_scenes):
        rng = np.random.default_rng([seed, i])
        env = EnvironmentConfig.random(rng) if env_mode == "random" else EnvironmentConfig.preset(env_mode)
        scene_sensor = sensor
        if threshold_jitter:
            scene_sensor = replace(
                sensor, point_threshold_db=float(rng.uniform(-55, -45)), noise_margin_db=float(rng.uniform(10, 18))
            )
        scene = random_scene(rng, sim, sensor)
        frame = simulate_sweep(scene, scene_sensor, env, sim, sweep, rng, timestamp=float(i), scene_id=i)
        if save_frames:
            frame.save(out / "scenes" / f"scene_{i:05d}.npz")
        clusters, _ = extract_clusters(frame, eps=eps, min_samples=min_samples, mode=seg_mode)
        for c in clusters:
            if c.label < 0:
                continue  # unlabeled (cannot happen for synthetic frames)
            pts.append(resample(c.points, n_points, rng))
            feats.append(cluster_features(c.points))
            labels.append(c.label)
            scene_ids.append(i)
            purity.append(c.purity)
            envs.append(env.name)

    labels_arr = np.asarray(labels, np.int16)
    np.savez_compressed(
        out / "clusters.npz",
        points=np.asarray(pts, np.float32).reshape(-1, n_points, 4),
        features=np.asarray(feats, np.float32).reshape(-1, len(FEATURE_NAMES)),
        labels=labels_arr,
        scene_ids=np.asarray(scene_ids, np.int32),
        purity=np.asarray(purity, np.float32),
        env=np.asarray(envs, dtype="U16"),
    )
    manifest = {
        "generator": f"sonar_perception {__version__}",
        "created": date.today().isoformat(),
        "n_scenes": n_scenes,
        "seed": seed,
        "env_mode": env_mode,
        "n_points": n_points,
        "dbscan": {"mode": seg_mode, "eps": eps, "min_samples": min_samples},
        "sensor": asdict(sensor),
        "threshold_jitter": threshold_jitter,
        "sweep": asdict(sweep),
        "sim": asdict(sim),
        "n_clusters": int(len(labels_arr)),
        "class_counts": {CLASSES[k]: int((labels_arr == k).sum()) for k in CLASSES},
        "mean_purity": float(np.mean(purity)) if purity else None,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def load_clusters(data_dir: str | Path) -> dict[str, np.ndarray]:
    with np.load(Path(data_dir) / "clusters.npz") as z:
        return {k: z[k] for k in z.files}


def split_by_scene(scene_ids: np.ndarray, test_frac: float = 0.2, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Boolean (train, test) masks; no scene appears in both."""
    scenes = np.unique(scene_ids)
    rng = np.random.default_rng(seed)
    test_scenes = rng.choice(scenes, max(1, int(round(len(scenes) * test_frac))), replace=False)
    test = np.isin(scene_ids, test_scenes)
    return ~test, test
