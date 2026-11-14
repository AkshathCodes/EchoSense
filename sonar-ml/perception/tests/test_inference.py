"""Noise class, detections format, and the detect pipeline."""

import json

import numpy as np

from sonar_perception.baseline import run_baseline
from sonar_perception.dataset import generate, load_clusters
from sonar_perception.inference import ForestClassifier, run_detect
from sonar_perception.sim import CLASSES, NOISE_CLASS
from sonar_perception.sources import SyntheticSource


def test_noise_class_present_with_jitter(tmp_path):
    generate(tmp_path, n_scenes=15, seed=0, n_points=64, save_frames=False)
    labels = load_clusters(tmp_path)["labels"]
    assert (labels == NOISE_CLASS).any()
    assert set(np.unique(labels)) <= set(CLASSES)


def test_detect_writes_valid_json(tmp_path):
    data = tmp_path / "train"
    generate(data, n_scenes=20, seed=0, n_points=64, save_frames=False)
    run_baseline(data, verbose=False)
    clf = ForestClassifier(data / "baseline_rf.joblib")
    out = tmp_path / "dets"
    summary = run_detect(SyntheticSource(n_frames=3, seed=999), clf, out, verbose=False)
    assert summary["n_frames"] == 3
    assert 0.0 <= summary["cluster_accuracy_vs_gt"] <= 1.0
    d = json.loads((out / "detections_00000.json").read_text())
    assert d["format_version"] == "0.1"
    for det in d["detections"]:
        assert det["class"] in CLASSES.values() and det["class"] != "noise"
        assert abs(sum(det["probs"].values()) - 1.0) < 1e-2
        assert len(det["centroid"]) == 3 and det["range_m"] > 0
    ranges = [det["range_m"] for det in d["detections"]]
    assert ranges == sorted(ranges)


def test_holdout_preset_never_sampled_randomly():
    from sonar_perception.config import HOLDOUT_PRESETS, EnvironmentConfig

    rng = np.random.default_rng(0)
    names = {EnvironmentConfig.random(rng).name for _ in range(200)}
    assert not names & set(HOLDOUT_PRESETS)
    assert EnvironmentConfig.preset("extreme").temperature_c > 150


def test_doorway_in_wall_creates_wall_segment():
    from dataclasses import replace

    from sonar_perception.config import SensorConfig, SimConfig
    from sonar_perception.sim.scene import build_object

    objs = build_object("doorway", np.random.default_rng(0), 0.05, 3.0, 0.0, 0.0, doorway_in_wall_prob=1.0)
    assert [o.name for o in objs] == ["doorway", "wall_segment"]
    assert replace(SimConfig(), floor_prob=0.0).floor_prob == 0.0 and SensorConfig().noise_reference > 0


def test_bias_raises_person_share():
    from sonar_perception.inference import BiasedClassifier, parse_bias

    class Fixed:
        name = "fixed"

        def predict_proba(self, clusters):
            return np.tile([0.0, 0.0, 0.5, 0.0, 0.4, 0.1], (len(clusters), 1))

    biased = BiasedClassifier(Fixed(), parse_bias(["person=2"]))
    p = biased.predict_proba([np.zeros((5, 4))])
    assert int(p.argmax()) == CLASSES_IDS_PERSON and abs(p.sum() - 1) < 1e-9


CLASSES_IDS_PERSON = 4


def test_tilt_keeps_points_in_level_frame():
    from dataclasses import replace

    from sonar_perception.config import EnvironmentConfig, SensorConfig, SimConfig
    from sonar_perception.sim import shapes
    from sonar_perception.sim.scene import Scene
    from sonar_perception.sources import simulate_frame

    wall = shapes.place(shapes.wall_local(3.0, 2.6, 0.03), 0, "wall", 3.0, 0.0, 0.0)
    xs = []
    for tilt in (0.0, 15.0):
        f = simulate_frame(Scene([wall]), replace(SensorConfig(), tilt_deg=tilt), EnvironmentConfig(multipath_rate=0.0), SimConfig(), np.random.default_rng(0))
        xs.append(np.median(f.points[f.point_labels == 0, 0]))
        assert f.meta["tilt_deg"] == tilt
    assert abs(xs[0] - xs[1]) < 0.1  # wall stays ~3 m ahead in the level frame


def test_diagnose_outcomes_cover_all_people(tmp_path):
    from sonar_perception.diagnostics import object_outcomes, summarize

    data = tmp_path / "d"
    generate(data, n_scenes=15, seed=0, n_points=64, save_frames=False)
    run_baseline(data, verbose=False)
    frames = list(SyntheticSource(n_frames=6, seed=5))
    rows = object_outcomes(frames, ForestClassifier(data / "baseline_rf.joblib"), "person")
    n_people = sum(o["class_id"] == 4 for f in frames for o in f.meta["object_list"])
    assert len(rows) == n_people
    s = summarize(rows)
    assert abs(sum(v for k, v in s["overall"].items() if k != "n") - 1.0) < 0.01 or not rows
