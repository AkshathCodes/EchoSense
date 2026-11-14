"""End-to-end: sim -> volume -> points -> clusters -> dataset -> baseline."""

import json

import numpy as np

from sonar_perception import views
from sonar_perception.baseline import run_baseline
from sonar_perception.config import EnvironmentConfig, SensorConfig, SimConfig
from sonar_perception.dataset import generate, load_clusters, split_by_scene
from sonar_perception.features import FEATURE_NAMES, cluster_features
from sonar_perception.grid import cartesian_to_spherical, spherical_to_cartesian
from sonar_perception.segmentation import extract_clusters
from sonar_perception.sim import shapes
from sonar_perception.sim.scene import Scene
from sonar_perception.sources import RecordedSource, SyntheticSource, simulate_frame


def test_spherical_roundtrip():
    xyz = np.random.default_rng(0).uniform(-3, 3, (100, 3)) + np.array([4.0, 0, 0])
    np.testing.assert_allclose(spherical_to_cartesian(*cartesian_to_spherical(xyz)), xyz, atol=1e-9)


def test_synthetic_frame_has_labeled_points():
    f = SyntheticSource(n_frames=1, seed=3).frame(0)
    assert f.points.shape[1] == 4 and len(f.points) > 100
    assert f.volume.shape == f.grid.shape
    assert set(np.unique(f.point_labels)) - {-1}  # some real labels


def test_two_separated_objects_give_two_clusters():
    sp = SimConfig().sample_spacing_m
    a = shapes.place(shapes.box((0.5, 0.6, 1.4), sp), 2, "furniture", 2.0, 0.9, 0.0)
    b = shapes.place(shapes.box((0.5, 0.6, 1.4), sp), 2, "furniture", 2.5, -1.0, 0.0)
    f = simulate_frame(Scene([a, b]), SensorConfig(), EnvironmentConfig(multipath_rate=0.0), SimConfig(), np.random.default_rng(0))
    clusters, _ = extract_clusters(f)
    real = [c for c in clusters if c.label == 2]
    assert len(real) == 2
    assert {c.instance for c in real} == {0, 1}


def test_features_and_views_shapes():
    pts = np.random.default_rng(0).uniform(0, 1, (50, 4)).astype(np.float32) + np.array([2, 0, -0.5, 0], np.float32)
    assert cluster_features(pts).shape == (len(FEATURE_NAMES),)
    rng = np.random.default_rng(0)
    assert views.pointset(pts, 64, rng).shape == (64, 5)
    assert views.bev(pts).shape == (4, 32, 32)
    assert views.voxels(pts).shape == (2, 16, 16, 16)


def test_generate_split_and_baseline(tmp_path):
    m = generate(tmp_path, n_scenes=12, seed=0, n_points=64)
    assert m["n_clusters"] > 10
    d = load_clusters(tmp_path)
    assert d["points"].shape[1:] == (64, 4)
    tr, te = split_by_scene(d["scene_ids"], 0.25, 0)
    assert not set(d["scene_ids"][tr]) & set(d["scene_ids"][te])
    metrics = run_baseline(tmp_path, verbose=False)
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert json.loads((tmp_path / "manifest.json").read_text())["n_scenes"] == 12
    frames = list(RecordedSource(tmp_path / "scenes"))
    assert len(frames) == 12 and frames[0].meta["source"] == "synthetic"
