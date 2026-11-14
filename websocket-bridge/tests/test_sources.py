"""Recorded-source tests use locally generated SIMULATED NPZ fixtures."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from sonar_bridge.protocol import encode_sonar_frame
from sonar_bridge.sources import recorded_messages


def save_frame(path, *, points=None):
    np.savez_compressed(path, points=np.array([[2, 0, 0, 5]] if points is None else points, dtype=np.float32),
                        timestamp=np.array(1.0),
                        meta=np.array(json.dumps({"format_version": "0.2", "source": "synthetic",
                                                 "sensor_id": "SIMULATED-recording-fixture"})))


def test_recorded_npz_and_associated_detection_document(tmp_path):
    save_frame(tmp_path / "frame.npz")
    doc = {"format_version": "0.1", "frame": {"timestamp": 1.0, "source": "synthetic",
           "sensor_id": "SIMULATED-recording-fixture", "scene_id": None, "conditions": None,
           "n_points": 1}, "model": "SIMULATED-empty-test-fixture", "detections": []}
    (tmp_path / "detections.json").write_text(json.dumps(doc))
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps({"frame": "frame.npz", "detections": "detections.json"}) + "\n" +
                        json.dumps({"frame": "frame.npz"}) + "\n")
    messages = [json.loads(text) for text in recorded_messages(manifest)]
    assert len(messages) == 2
    assert [m["sequence"] for m in messages] == [0, 1]
    assert messages[0]["source"] == "recorded"
    assert messages[0]["acquisition_source"] == "simulated"
    assert messages[0]["frame"]["points"] == [[2.0, 0.0, 0.0, 5.0]]
    assert messages[0]["detections"] == doc
    assert messages[1]["detections"] is None


@pytest.mark.parametrize("entry", [{"frame": "../escape.npz"}, {"frame": "bad.json"},
                                     {"frame": "frame.npz", "extra": True}, {}])
def test_invalid_manifest(tmp_path, entry):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps(entry) + "\n")
    with pytest.raises(ValueError):
        list(recorded_messages(manifest))


@pytest.mark.parametrize("points", [np.empty((0, 4)), np.array([[2, 0, 0, 1]], dtype=np.float32)])
def test_numpy_sonar_frame_adapter(points):
    frame = SimpleNamespace(points=points, timestamp=1.0,
                            meta={"format_version": "0.2", "source": "synthetic"})
    assert json.loads(encode_sonar_frame(frame, 0))["frame"]["points"] == points.tolist()


@pytest.mark.parametrize("points", [np.empty((0,)), np.zeros((1, 3)), np.zeros((1, 2, 4))])
def test_numpy_shape_validation(points):
    frame = SimpleNamespace(points=points, timestamp=1.0,
                            meta={"format_version": "0.2", "source": "synthetic"})
    with pytest.raises(ValueError):
        encode_sonar_frame(frame, 0)
