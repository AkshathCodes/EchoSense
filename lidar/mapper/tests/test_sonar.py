"""HC-SR04 cross-check logic. All inputs here are SYNTHETIC."""
import json

import numpy as np

from lidar_mapper.server import LiveMapper, SONAR_STRENGTH
from lidar_mapper.mapper import Mapper
from lidar_mapper.sonar import SonarFusion, compare, cone_ranges, load_sidecar, parse_line

K = np.array([[210.0, 0, 160.0], [0, 210.0, 120.0], [0, 0, 1.0]])
EYE, ZERO = np.eye(3), np.zeros(3)


def wall(distance: float, shape=(240, 320)) -> np.ndarray:
    return np.full(shape, distance, dtype=np.float32)


def test_parse_line_accepts_meters_and_treats_everything_else_as_no_reading():
    assert parse_line("1.234\r\n") == 1.234
    for bad in ("timeout", "", "abc", "-1", "0", "nan", "inf"):
        assert parse_line(bad) is None


def test_cone_holds_only_the_centre_of_the_frame_and_uses_ray_length():
    depth = wall(2.0)
    depth[:, :100] = 0.5                      # something near, far off to the left of the cone
    ranges, valid = cone_ranges(depth, K, 10.0)
    assert valid == 1.0 and 2.0 <= ranges.min() and ranges.max() < 2.0 / np.cos(np.radians(10.5))
    shifted, _ = cone_ranges(depth, K, 10.0, offset_deg=(-25.0, 0.0))
    assert shifted.min() < 0.6                # aiming the cone left now finds the near object


def test_compare_states():
    ranges, _ = cone_ranges(wall(2.0), K, 10.0)
    assert compare(2.03, ranges, 1.0)["state"] == "agree"
    assert compare(0.90, ranges, 1.0)["state"] == "sonar_closer"       # glass 0.9 m ahead, wall behind
    assert compare(1.85, ranges, 1.0)["state"] == "agree"              # too close to call
    assert compare(3.40, ranges, 1.0)["state"] == "sonar_farther"
    assert compare(None, ranges, 1.0)["state"] == "no_sonar"
    assert compare(5.5, ranges, 1.0)["state"] == "no_sonar"            # beyond the sensor's range
    assert compare(1.2, np.array([]), 0.0)["state"] == "lidar_no_return"
    result = compare(0.90, ranges, 1.0)
    assert result["range_m"] == 0.9 and abs(result["lidar_near_m"] - 2.0) < 0.02


def test_steady_disagreement_becomes_one_surface_point_on_the_axis():
    fusion = SonarFusion(persist=3)
    R = np.array([[0.0, 0, 1], [-1, 0, 0], [0, -1, 0]])     # camera looks along world +x
    for step, reading in enumerate([0.94, 0.96, 0.95, 0.94]):
        fusion.update(reading, at=step * 0.1)
        status = fusion.observe(wall(2.5), K, R, np.array([1.0, 2.0, 0.5]), tracking=True, now=step * 0.1)
    assert status["state"] == "sonar_closer" and status["surface_points"] == 1   # same 10 cm cell
    assert np.allclose(fusion.surface[0], [1.95, 2.0, 0.5], atol=0.02)


def test_no_surface_point_without_tracking_or_when_readings_jump():
    lost = SonarFusion()
    for step in range(5):
        lost.update(0.9, at=step * 0.1)
        lost.observe(wall(2.5), K, EYE, ZERO, tracking=False, now=step * 0.1)
    assert lost.surface == []
    jumpy = SonarFusion()
    for step, reading in enumerate([0.6, 1.4, 0.7, 1.5, 0.6]):
        jumpy.update(reading, at=step * 0.1)
        jumpy.observe(wall(2.5), K, EYE, ZERO, tracking=True, now=step * 0.1)
    assert jumpy.surface == []


def test_stale_readings_are_ignored_and_agreement_adds_nothing():
    fusion = SonarFusion(max_age=0.35)
    fusion.update(0.9, at=0.0)
    assert fusion.observe(wall(2.5), K, EYE, ZERO, tracking=True, now=1.0)["state"] == "no_sonar"
    for step in range(5):
        fusion.update(2.5, at=2 + step * 0.1)
        status = fusion.observe(wall(2.5), K, EYE, ZERO, tracking=True, now=2 + step * 0.1)
    assert status["state"] == "agree" and fusion.surface == []


def test_mount_and_aim_offsets_move_the_surface_point():
    fusion = SonarFusion(persist=1, mount_m=(0.02, -0.03, 0.0), offset_deg=(0.0, 0.0))
    fusion.update(1.0, at=0.0)
    fusion.observe(wall(3.0), K, EYE, ZERO, tracking=True, now=0.0)
    assert np.allclose(fusion.surface[0], [0.02, -0.03, 1.0])


def test_sidecar_round_trip_and_viewer_envelope(tmp_path):
    path = tmp_path / "scan.esd.sonar.jsonl"
    fusion = SonarFusion(persist=1)
    with open(path, "w", encoding="utf-8") as fusion.sidecar:
        for seq, reading in enumerate([0.9, None, 2.4]):
            fusion.update(reading, at=float(seq))
            fusion.observe(wall(2.5), K, EYE, ZERO, tracking=True, seq=seq, now=float(seq))
    assert load_sidecar(str(path)) == {0: 0.9, 1: None, 2: 2.4}

    live = LiveMapper(Mapper(), verbose=False)
    live.sonar = fusion
    message = json.loads(live.snapshot())
    assert message["frame"]["meta"]["sonar"]["state"] == "agree"
    assert message["frame"]["meta"]["sonar"]["surface_points"] == 1
    assert message["frame"]["points"][-1][3] == SONAR_STRENGTH
    plain = json.loads(LiveMapper(Mapper(), verbose=False).snapshot())
    assert "sonar" not in plain["frame"]["meta"]            # unchanged output when no sonar is attached


def test_serial_reader_feeds_readings_from_a_port():
    """Stands in for the microcontroller with a pseudo-terminal. No hardware involved."""
    import os
    import time

    import pytest
    pytest.importorskip("serial")
    pty = pytest.importorskip("pty")
    from lidar_mapper.sonar import SerialSonar

    controller, device = pty.openpty()
    fusion = SonarFusion()
    reader = SerialSonar(fusion, os.ttyname(device), 115200)
    reader.start()
    os.write(controller, b"0.512\r\ntimeout\r\ngarbage\r\n1.250\r\n")
    for _ in range(100):
        if fusion.readings >= 3:
            break
        time.sleep(0.02)
    assert fusion.readings == 3 and reader.bad == 1       # two distances, one timeout, one rejected line
    assert fusion.latest()[0] == 1.25
