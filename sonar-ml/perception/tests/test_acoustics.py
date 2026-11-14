"""Physics sanity checks for the reflection model (ADR-0003)."""

import math
from dataclasses import replace

import numpy as np

from sonar_perception.config import EnvironmentConfig, SensorConfig, SimConfig
from sonar_perception.sim import shapes
from sonar_perception.sim.acoustics import simulate_returns
from sonar_perception.sim.scene import Scene

SENSOR = SensorConfig()
SIM = SimConfig()
QUIET = EnvironmentConfig(multipath_rate=0.0)


def _wall(x, yaw, y=0.0):
    return shapes.place(shapes.wall_local(3.0, 2.6, SIM.sample_spacing_m), 0, "wall", x, y, yaw)


def _sim(objects, env=QUIET):
    return simulate_returns(Scene(objects), SENSOR, env, SIM, np.random.default_rng(0))


def test_small_panel_dims_when_turned_away():
    # A small panel has no specular point once rotated, so it fades sharply.
    # (A LARGE wall rotated 30° stays bright: the perpendicular from the sensor
    # still lands on it. See docs/log/2026-11-13-ideation-and-research.md §9.)
    sim = replace(SIM, edge_bonus=0.0)
    panel = lambda yaw: shapes.place(shapes.box((0.02, 0.6, 0.6), sim.sample_spacing_m), 2, "f", 3.0, 0.0, yaw)  # noqa: E731
    amp = lambda yaw: simulate_returns(Scene([panel(yaw)]), SENSOR, QUIET, sim, np.random.default_rng(0)).amplitude.sum()  # noqa: E731
    assert amp(0.0) > 5 * amp(math.radians(60))


def test_side_wall_parallel_to_line_of_sight_is_dim():
    back = _sim([_wall(3.0, 0.0)]).amplitude.sum()
    side = _sim([_wall(3.0, math.pi / 2, y=1.8)]).amplitude.sum()
    assert back > 3 * side


def test_occlusion_hides_object_behind_wall():
    sp = SIM.sample_spacing_m
    cab = shapes.place(shapes.box((0.5, 0.8, 1.6), sp), 2, "furniture", 4.0, 0.0, 0.0)
    alone = (_sim([cab]).label == 2).sum()
    hidden = (_sim([_wall(2.0, 0.0), cab]).label == 2).sum()
    assert alone > 0 and hidden < 0.05 * alone


def test_warm_air_reads_closer():
    cold = _sim([_wall(3.0, 0.0)], EnvironmentConfig(temperature_c=20.0, multipath_rate=0.0))
    warm = _sim([_wall(3.0, 0.0)], EnvironmentConfig(temperature_c=100.0, multipath_rate=0.0))
    assert np.median(warm.range_m) < np.median(cold.range_m)


def test_out_of_fov_object_invisible():
    behind = _wall(-3.0, 0.0)
    assert len(_sim([behind])) == 0


def test_ghosts_are_noise_and_behind():
    env = EnvironmentConfig(multipath_rate=0.2)
    r = simulate_returns(Scene([_wall(3.0, 0.0)]), SENSOR, env, SIM, np.random.default_rng(1))
    ghosts = r.label == shapes.NOISE
    assert ghosts.any()
    assert np.median(r.range_m[ghosts]) > np.median(r.range_m[~ghosts])
