"""Ping averaging and multi-view sweep fusion (ADR-0013)."""

import math
from dataclasses import replace

import numpy as np

from sonar_perception.config import EnvironmentConfig, SensorConfig, SimConfig, SweepConfig
from sonar_perception.sim import shapes
from sonar_perception.sim.scene import Scene
from sonar_perception.sources import SyntheticSource, simulate_frame, simulate_sweep

SP = SimConfig().sample_spacing_m


def _lying_person(x=3.0, y=0.3, yaw=0.7):
    rng = np.random.default_rng(0)
    while True:
        body, pose = shapes.person_local(rng, SP)
        if pose == "lying":
            return shapes.place(body, 4, "person", x, y, yaw, variant=pose)


def test_ping_averaging_lowers_noise_floor():
    grid_med = []
    for pings in (1, 16):
        f = simulate_frame(Scene([]), replace(SensorConfig(), pings_averaged=pings), EnvironmentConfig.preset("heavy"), SimConfig(), np.random.default_rng(0))
        grid_med.append(float(np.median(f.volume)))
    assert grid_med[1] < 0.3 * grid_med[0]  # sqrt(16) = 4x lower


def test_ping_averaging_reveals_more_of_weak_target():
    env = EnvironmentConfig.preset("fog")
    n = [
        (simulate_frame(Scene([_lying_person()]), replace(SensorConfig(), pings_averaged=p), env, SimConfig(), np.random.default_rng(1)).point_labels == 4).sum()
        for p in (1, 8)
    ]
    assert n[1] > n[0]


def test_sweep_keeps_geometry_in_reference_frame():
    wall = shapes.place(shapes.wall_local(3.0, 2.6, SP), 0, "wall", 3.0, 0.0, 0.0)
    env = EnvironmentConfig(multipath_rate=0.0)
    single = simulate_frame(Scene([wall]), SensorConfig(), env, SimConfig(), np.random.default_rng(0))
    swept = simulate_sweep(Scene([wall]), SensorConfig(), env, SimConfig(), SweepConfig(3, 40.0, 0.4), np.random.default_rng(0))
    xs = [np.median(f.points[f.point_labels == 0, 0]) for f in (single, swept)]
    assert abs(xs[0] - xs[1]) < 0.1
    assert swept.meta["sweep"]["n_poses"] == 3


def test_sweep_sees_more_of_lying_person():
    env = EnvironmentConfig.preset("fog")
    obj = _lying_person()
    single = simulate_frame(Scene([obj]), SensorConfig(), env, SimConfig(), np.random.default_rng(2))
    swept = simulate_sweep(Scene([obj]), SensorConfig(), env, SimConfig(), SweepConfig(5, 60.0), np.random.default_rng(2))
    assert (swept.point_labels == 4).sum() > (single.point_labels == 4).sum()


def test_sweep_fuse_is_voxel_unique():
    f = SyntheticSource(n_frames=1, seed=3, sweep=SweepConfig(3, 40.0)).frame(0)
    keys = np.floor(f.points[:, :3] / 0.05).astype(np.int64)
    assert len(np.unique(keys, axis=0)) == len(keys)
    assert math.isclose(f.meta["sweep"]["yaw_span_deg"], 40.0)


def test_min_views_drops_single_view_points():
    from sonar_perception.sources.synthetic import _voxel_fuse

    pts = np.array([[1.0, 0, 0, 5], [1.01, 0, 0, 4], [3.0, 0, 0, 9]], np.float32)  # voxel A seen by poses 0+1, voxel B by pose 2 only
    labs, insts = np.zeros(3, np.int16), np.zeros(3, np.int32)
    poses = np.array([0, 1, 2])
    p1, _, _ = _voxel_fuse(pts, labs, insts, 0.05, poses, min_views=1)
    p2, _, _ = _voxel_fuse(pts, labs, insts, 0.05, poses, min_views=2)
    assert len(p1) == 2 and len(p2) == 1 and abs(p2[0, 0] - 1.0) < 0.05
