"""Transport contract tests; fixtures are explicitly simulated, not classifier results."""
import copy
import json
from types import SimpleNamespace

import pytest

from sonar_bridge.protocol import (CLASSES, MAX_DETECTIONS, MAX_MESSAGE_BYTES,
                                   MAX_POINTS, encode_frame, encode_sonar_frame)
from sonar_bridge.sources import demo_messages


def sample():
    return dict(points=[[2.0, -0.5, 0.25, 5.0]], timestamp=12.0, sequence=0,
                meta={"format_version": "0.2", "source": "synthetic", "sensor_id": "TEST-SIMULATED"})


def detection_document():
    # Schema fixture only. Never emitted as a real classifier result.
    return {"format_version": "0.1",
            "frame": {"timestamp": 12.0, "source": "synthetic", "sensor_id": "TEST-SIMULATED",
                      "scene_id": None, "conditions": None, "n_points": 1},
            "model": "SIMULATED-test-fixture",
            "detections": [{"id": 0, "class": "wall", "class_id": 0, "confidence": 0.8,
                            "probs": dict(zip(CLASSES, (0.8, 0.0, 0.1, 0.1, 0.0, 0.0))),
                            "centroid": [2.0, -0.5, 0.25], "range_m": 2.077,
                            "azimuth_deg": -14.04, "elevation_deg": 6.91,
                            "bbox_min": [2.0, -0.5, 0.25], "bbox_max": [2.0, -0.5, 0.25],
                            "n_points": 1, "mean_intensity": 5.0, "gt_class": "wall"}]}


def test_envelope_and_immutable_inputs():
    inputs = sample()
    before = copy.deepcopy(inputs)
    message = json.loads(encode_frame(**inputs))
    assert inputs == before
    assert set(message) == {"protocol_version", "type", "sequence", "timestamp", "source",
                            "acquisition_source", "frame", "detections"}
    assert message["protocol_version"] == "0.1"
    assert message["type"] == "sonar_frame"
    assert message["sequence"] == 0
    assert message["timestamp"] == 12.0
    assert message["frame"] == {"format_version": "0.2", "meta": inputs["meta"], "points": inputs["points"]}
    assert message["detections"] is None


@pytest.mark.parametrize("raw, label", [("synthetic", "simulated"), ("recorded", "recorded"), ("live", "live")])
def test_source_labels(raw, label):
    inputs = sample()
    inputs["meta"]["source"] = raw
    message = json.loads(encode_frame(**inputs))
    assert message["source"] == message["acquisition_source"] == label
    assert message["frame"]["meta"]["source"] == raw


def test_replay_does_not_hide_simulated_origin():
    message = json.loads(encode_frame(**sample(), replay=True))
    assert message["source"] == "recorded"
    assert message["acquisition_source"] == "simulated"


def test_detections_preserved_exactly():
    doc = detection_document()
    before = copy.deepcopy(doc)
    message = json.loads(encode_frame(**sample(), detections=doc))
    assert message["detections"] == doc == before


@pytest.mark.parametrize("points", [None, {}, [1, 2, 3, 4], [[1, 2, 3]], [[1, 2, 3, 4, 5]],
                                      [[1, 2, "3", 4]], [[True, 2, 3, 4]], [[1, 2, 3, -1]]])
def test_malformed_points(points):
    inputs = sample()
    inputs["points"] = points
    with pytest.raises(ValueError):
        encode_frame(**inputs)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("column", range(4))
def test_nonfinite_point_values(bad, column):
    inputs = sample()
    inputs["points"][0][column] = bad
    with pytest.raises(ValueError):
        encode_frame(**inputs)


@pytest.mark.parametrize("field, value", [("timestamp", float("nan")), ("timestamp", True),
                                         ("sequence", -1), ("sequence", 0.5), ("sequence", True)])
def test_invalid_metadata_scalars(field, value):
    inputs = sample()
    inputs[field] = value
    with pytest.raises(ValueError):
        encode_frame(**inputs)


@pytest.mark.parametrize("field, value", [("source", "simulated"), ("source", "unknown"),
                                         ("format_version", "0.1"), ("format_version", "1.0"),
                                         ("conditions", float("inf")), ("conditions", object())])
def test_invalid_frame_metadata(field, value):
    inputs = sample()
    inputs["meta"][field] = value
    with pytest.raises(ValueError):
        encode_frame(**inputs)


@pytest.mark.parametrize("key, value", [("confidence", 1.1), ("confidence", float("nan")),
                                       ("centroid", [1, 2]), ("bbox_max", [1, -0.5, 0.25]),
                                       ("class", "person"), ("class_id", 99), ("id", -1),
                                       ("probs", {}), ("range_m", -1), ("extra", 42)])
def test_invalid_detection_fields(key, value):
    doc = detection_document()
    doc["detections"][0][key] = value
    with pytest.raises(ValueError):
        encode_frame(**sample(), detections=doc)


@pytest.mark.parametrize("field, value", [("timestamp", 13), ("n_points", 2), ("source", "live"),
                                         ("sensor_id", "other"), ("scene_id", 4)])
def test_unassociated_detections_rejected(field, value):
    doc = detection_document()
    doc["frame"][field] = value
    with pytest.raises(ValueError):
        encode_frame(**sample(), detections=doc)


def test_unknown_detection_version():
    doc = detection_document()
    doc["format_version"] = "0.2"
    with pytest.raises(ValueError):
        encode_frame(**sample(), detections=doc)


def test_live_ground_truth_is_rejected():
    inputs = sample()
    inputs["meta"]["source"] = "live"
    doc = detection_document()
    doc["frame"]["source"] = "live"
    with pytest.raises(ValueError):
        encode_frame(**inputs, detections=doc)


def test_empty_and_bounded_points():
    inputs = sample()
    inputs["points"] = []
    assert json.loads(encode_frame(**inputs))["frame"]["points"] == []
    inputs["points"] = [[0, 0, 0, 1]] * (MAX_POINTS + 1)
    with pytest.raises(ValueError):
        encode_frame(**inputs)


def test_detection_limit():
    doc = detection_document()
    doc["detections"] *= MAX_DETECTIONS + 1
    with pytest.raises(ValueError):
        encode_frame(**sample(), detections=doc)


def test_byte_limit():
    inputs = sample()
    inputs["meta"]["conditions"] = "x" * MAX_MESSAGE_BYTES
    with pytest.raises(ValueError):
        encode_frame(**inputs)


def test_adapter_preserves_frame_and_detection_values():
    inputs = sample()
    frame = SimpleNamespace(points=inputs["points"], timestamp=inputs["timestamp"], meta=inputs["meta"])
    assert encode_sonar_frame(frame, 0, detection_document()) == encode_frame(**inputs, detections=detection_document())


def test_demo_is_deterministic_and_explicitly_simulated():
    first, second = demo_messages(), demo_messages()
    for sequence in range(3):
        a, b = next(first), next(second)
        assert a == b
        message = json.loads(a)
        assert message["source"] == message["acquisition_source"] == "simulated"
        assert message["frame"]["meta"]["source"] == "synthetic"
        assert message["detections"] is None
        assert message["timestamp"] == sequence / 10
        assert message["sequence"] == sequence
        assert len(message["frame"]["points"]) == 45
        assert all(p[0] == 2 for p in message["frame"]["points"])
    first.close()
    second.close()


@pytest.mark.parametrize("value", [{1: "coerced key"}, (1, 2), {"nested": float("nan")}])
def test_metadata_rejects_implicit_json_coercion(value):
    inputs = sample()
    inputs["meta"]["conditions"] = value
    with pytest.raises(ValueError):
        encode_frame(**inputs)


def test_deep_metadata_rejected():
    inputs = sample()
    value = []
    for _ in range(30):
        value = [value]
    inputs["meta"]["conditions"] = value
    with pytest.raises(ValueError):
        encode_frame(**inputs)


def test_nonstring_source_rejected():
    inputs = sample()
    inputs["meta"]["source"] = []
    with pytest.raises(ValueError):
        encode_frame(**inputs)
