"""Proposed JSON transport, independent of Rishi's perception package."""
from __future__ import annotations

import json
import math
from typing import Any

MAX_POINTS = 20_000
MAX_DETECTIONS = 256
MAX_MESSAGE_BYTES = 2_000_000
CLASSES = ("wall", "doorway", "furniture", "debris", "person", "noise")
SOURCES = {"synthetic": "simulated", "recorded": "recorded", "live": "live"}


def number(value: Any, name: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite number")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be finite")
    return value


def integer(value: Any, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def vector(value: Any, size: int, name: str) -> None:
    if type(value) is not list or len(value) != size:
        raise ValueError(f"{name} must be an array of length {size}")
    for item in value:
        number(item, name)


def validate_points(points: Any) -> None:
    if type(points) is not list or len(points) > MAX_POINTS:
        raise ValueError("points must be a bounded array")
    for point in points:
        vector(point, 4, "point")
        if point[3] < 0:
            raise ValueError("SNR intensity must be nonnegative")


def validate_detections(document: Any, timestamp: float, meta: dict[str, Any], count: int) -> None:
    if document is None:
        return
    if type(document) is not dict or set(document) != {"format_version", "frame", "model", "detections"}:
        raise ValueError("unexpected detections document fields")
    if document["format_version"] != "0.1" or type(document["model"]) is not str:
        raise ValueError("expected detections v0.1 with model name")
    frame = document["frame"]
    required_frame = {"timestamp", "source", "sensor_id", "scene_id", "conditions", "n_points"}
    if type(frame) is not dict or set(frame) != required_frame:
        raise ValueError("unexpected detection frame fields")
    number(frame["timestamp"], "detection timestamp")
    integer(frame["n_points"], "detection frame n_points")
    conditions = meta.get("conditions")
    if isinstance(conditions, dict):
        conditions = conditions.get("name")
    expected = {"timestamp": timestamp, "source": meta["source"],
                "sensor_id": meta.get("sensor_id"), "scene_id": meta.get("scene_id"),
                "conditions": conditions, "n_points": count}
    if frame != expected:
        raise ValueError("detections do not match their associated frame")
    items = document["detections"]
    if type(items) is not list or len(items) > MAX_DETECTIONS:
        raise ValueError("detections must be a bounded array")
    required = {"id", "class", "class_id", "confidence", "probs", "centroid", "range_m",
                "azimuth_deg", "elevation_deg", "bbox_min", "bbox_max", "n_points", "mean_intensity"}
    seen = set()
    for det in items:
        if type(det) is not dict or not required <= det.keys() or det.keys() - required - {"gt_class"}:
            raise ValueError("unexpected detection fields")
        for key in ("id", "class_id", "n_points"):
            integer(det[key], key)
        if det["id"] in seen:
            raise ValueError("duplicate detection id")
        seen.add(det["id"])
        if det["class_id"] >= len(CLASSES) or det["class"] != CLASSES[det["class_id"]]:
            raise ValueError("class/class_id mismatch")
        if "gt_class" in det and (meta["source"] == "live" or det["gt_class"] not in CLASSES):
            raise ValueError("unexpected ground truth label")
        for key in ("confidence", "range_m", "azimuth_deg", "elevation_deg", "mean_intensity"):
            number(det[key], key)
        if not 0 <= det["confidence"] <= 1 or det["range_m"] < 0 or det["mean_intensity"] < 0:
            raise ValueError("invalid detection scalar")
        probs = det["probs"]
        if type(probs) is not dict or set(probs) != set(CLASSES):
            raise ValueError("expected probabilities for all documented classes")
        for probability in probs.values():
            if not 0 <= number(probability, "probability") <= 1:
                raise ValueError("invalid probability")
        for key in ("centroid", "bbox_min", "bbox_max"):
            vector(det[key], 3, key)
        if any(lo > hi for lo, hi in zip(det["bbox_min"], det["bbox_max"])):
            raise ValueError("inverted bounding box")


def validate_json(value: Any, depth: int = 0) -> None:
    """Reject implicit JSON coercions and deeply nested producer metadata."""
    if depth > 24:
        raise ValueError("JSON nesting exceeds limit")
    if value is None or type(value) in (str, bool):
        return
    if type(value) in (int, float):
        number(value, "JSON number")
        return
    if type(value) is list:
        for item in value:
            validate_json(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("JSON object keys must be strings")
            validate_json(item, depth + 1)
        return
    raise ValueError("unexpected non-JSON data")


def encode_frame(*, points: Any, timestamp: float, meta: dict[str, Any],
                 sequence: int, detections: Any = None, replay: bool = False) -> str:
    """Validate, preserve input values, and serialize a point-only frame envelope."""
    integer(sequence, "sequence")
    number(timestamp, "timestamp")
    if type(meta) is not dict or meta.get("format_version") != "0.2":
        raise ValueError("expected SonarFrame v0.2 metadata")
    if type(meta.get("source")) is not str or meta["source"] not in SOURCES:
        raise ValueError("unknown acquisition source")
    validate_json(meta)
    validate_points(points)
    validate_detections(detections, timestamp, meta, len(points))
    validate_json(detections)
    origin = SOURCES[meta["source"]]
    message = {"protocol_version": "0.1", "type": "sonar_frame", "sequence": sequence,
               "timestamp": timestamp, "source": "recorded" if replay else origin,
               "acquisition_source": origin,
               "frame": {"format_version": "0.2", "meta": meta, "points": points},
               "detections": detections}
    # JSON round-trip checks also reject nonfinite values hidden in metadata.
    try:
        text = json.dumps(message, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ValueError("frame must contain finite JSON data") from exc
    if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ValueError("serialized message exceeds byte limit")
    return text


def encode_sonar_frame(frame: Any, sequence: int, detections_document: Any = None,
                       *, replay: bool = False) -> str:
    """Duck-typed adapter for actual SonarFrame objects; no perception import.

    Supply the unmodified frame_detections_dict(...) output, or None.
    No classifier is invoked, no rotations or intensity normalization occur.
    """
    points = frame.points
    if hasattr(points, "shape"):
        if len(points.shape) != 2 or points.shape[1] != 4 or points.shape[0] > MAX_POINTS:
            raise ValueError("points must have bounded [N, 4] shape")
        points = points.tolist()
    return encode_frame(points=points, timestamp=frame.timestamp, meta=frame.meta,
                        sequence=sequence, detections=detections_document, replay=replay)
