"""Explicitly simulated demo and lazy recorded SonarFrame point replay."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from collections.abc import Iterator
from typing import Any

from .protocol import encode_frame, encode_sonar_frame

MAX_FILE_BYTES = 16_000_000


def demo_messages() -> Iterator[str]:
    """Deterministic SIMULATED wall at x=2; no classifier detections invented."""
    sequence = 0
    points = [[2.0, y / 4, z / 4, 5.0] for z in range(-2, 3) for y in range(-4, 5)]
    while True:
        yield encode_frame(points=points, timestamp=sequence / 10,
                           meta={"format_version": "0.2", "source": "synthetic",
                                 "sensor_id": "SIMULATED-wall-demo", "tilt_deg": 0.0},
                           sequence=sequence, detections=None)
        sequence += 1


def read_json(path: Path) -> Any:
    with path.open("rb") as file:
        raw = file.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("JSON file exceeds size limit")
    return json.loads(raw)


def local_file(folder: Path, name: Any, suffix: str) -> Path:
    if type(name) is not str:
        raise ValueError("recording filename must be text")
    path = (folder / name).resolve()
    if not path.is_relative_to(folder.resolve()) or path.suffix != suffix:
        raise ValueError("recording paths must stay within manifest directory")
    return path


def recorded_messages(manifest: Path) -> Iterator[str]:
    """Read JSONL manifest entries lazily; numpy is needed only for NPZ replay.

    Each entry: {"frame": "capture.npz", "detections": "detections_00000.json"}.
    Omit detections when unavailable; no guesses or filename-based pairing.
    """
    import numpy as np

    with manifest.open("rb") as file:
        sequence = 0
        while line := file.readline(MAX_FILE_BYTES + 1):
            if len(line) > MAX_FILE_BYTES:
                raise ValueError("manifest line exceeds size limit")
            entry = json.loads(line)
            if type(entry) is not dict or "frame" not in entry or entry.keys() - {"frame", "detections"}:
                raise ValueError("unexpected manifest entry")
            path = local_file(manifest.parent, entry["frame"], ".npz")
            # Inspect declared uncompressed size before loading arrays.
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("NPZ exceeds size limit")
            with zipfile.ZipFile(path) as archive:
                if sum(info.file_size for info in archive.infolist()) > 64_000_000:
                    raise ValueError("NPZ uncompressed size exceeds limit")
            with np.load(path, allow_pickle=False) as arrays:
                frame = SimpleNamespace(points=arrays["points"], timestamp=float(arrays["timestamp"]),
                                        meta=json.loads(str(arrays["meta"])))
            detections = None
            if "detections" in entry:
                detections = read_json(local_file(manifest.parent, entry["detections"], ".json"))
            yield encode_sonar_frame(frame, sequence, detections, replay=True)
            sequence += 1
