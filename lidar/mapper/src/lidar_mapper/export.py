"""Session export for the Databricks lakehouse (ADR-0016).

A recorded session (`.esd`, raw frames exactly as the phone sent them) is replayed
through the mapper and written as three files, one per Auto Loader stream:

  <out>/frames/<session_id>.parquet    one row per frame: raw depth (float16 bytes), intrinsics,
                                       IMU, and the mapper's pose for that frame
  <out>/maps/<session_id>.parquet      one row per map voxel (seen >= 2 times): x, y, z, hits, segment
  <out>/sessions/<session_id>.json     metadata, labels (e.g. lights=off), mapper settings, stats

Raw depth is kept so Databricks can reprocess sessions with a better mapper later.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import __version__, protocol
from .mapper import Mapper, floor_check
from .server import read_records

EXPORT_VERSION = "0.1"


def frames_schema():
    import pyarrow as pa

    f64 = pa.list_(pa.float64())
    return pa.schema([
        ("session_id", pa.string()), ("app_session", pa.int32()), ("frame_index", pa.int32()), ("seq", pa.int32()),
        ("t", pa.float64()), ("source", pa.string()), ("width", pa.int32()), ("height", pa.int32()),
        ("fx", pa.float32()), ("fy", pa.float32()), ("cx", pa.float32()), ("cy", pa.float32()),
        ("depth_f16", pa.binary()), ("confidence_u8", pa.binary()), ("valid_fraction", pa.float32()),
        ("n_points", pa.int32()), ("attitude", f64), ("attitude_ref", pa.string()), ("gravity", f64),
        ("rotation_rate", f64), ("user_accel", f64), ("ambient_lux", pa.float64()), ("arkit_tracking", pa.string()),
        ("pose_status", pa.string()), ("pose_R", f64), ("pose_t", f64), ("icp_rmse", pa.float64()),
        ("icp_inliers", pa.float64()), ("segment", pa.int32()),
    ])


def maps_schema():
    import pyarrow as pa

    return pa.schema([("session_id", pa.string()), ("segment", pa.int32()), ("x", pa.float32()), ("y", pa.float32()),
                      ("z", pa.float32()), ("hits", pa.int32())])


def session_id_for(path: Path) -> str:
    stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{re.sub(r'[^A-Za-z0-9_-]+', '-', path.stem)}-{stamp}"


def _f(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else float(x)


def _lst(a):
    return None if a is None else [float(v) for v in np.asarray(a).reshape(-1)]


@dataclass
class ExportResult:
    session_id: str
    frames_path: Path
    map_path: Path
    session_path: Path
    stats: dict


def export_session(esd: str | Path, out_dir: str | Path, labels: dict | None = None, notes: str = "",
                   mapper: Mapper | None = None, session_id: str | None = None) -> ExportResult:
    import pyarrow as pa
    import pyarrow.parquet as pq

    esd, out = Path(esd), Path(out_dir)
    sid = session_id or session_id_for(esd)
    m = mapper or Mapper()
    rows: dict[str, list] = {k: [] for k in frames_schema().names}
    statuses: Counter = Counter()
    app_session, last_seq, t0, t1 = 0, -1, None, None
    lux = {"lights_on_frames": 0}
    for i, msg in enumerate(read_records(esd)):
        f = protocol.decode(msg)
        if f.seq < last_seq:
            app_session += 1
        last_seq = f.seq
        t0 = f.t if t0 is None else t0
        t1 = f.t
        r = m.process(f)
        statuses[r.status] += 1
        h, w = f.depth.shape
        rec = {
            "session_id": sid, "app_session": app_session, "frame_index": i, "seq": f.seq, "t": f.t,
            "source": f.source, "width": w, "height": h, "fx": f.K[0, 0], "fy": f.K[1, 1], "cx": f.K[0, 2],
            "cy": f.K[1, 2], "depth_f16": np.nan_to_num(f.depth, nan=0.0).astype("<f2").tobytes(),
            "confidence_u8": f.confidence.tobytes() if f.confidence is not None else None,
            "valid_fraction": f.valid_fraction, "n_points": r.n_points, "attitude": _lst(f.attitude),
            "attitude_ref": f.attitude_ref, "gravity": _lst(f.gravity), "rotation_rate": _lst(f.rotation_rate),
            "user_accel": _lst(f.user_accel), "ambient_lux": _f(f.ambient_lux), "arkit_tracking": f.arkit_tracking,
            "pose_status": r.status, "pose_R": _lst(r.R), "pose_t": _lst(r.t), "icp_rmse": _f(r.rmse),
            "icp_inliers": _f(r.inlier_frac), "segment": len(m.segments) + m.merges,
        }
        for k, v in rec.items():
            rows[k].append(v)
    if not rows["seq"]:
        raise ValueError(f"{esd} has no frames")

    (out / "frames").mkdir(parents=True, exist_ok=True)
    (out / "maps").mkdir(parents=True, exist_ok=True)
    (out / "sessions").mkdir(parents=True, exist_ok=True)
    frames_path = out / "frames" / f"{sid}.parquet"
    pq.write_table(pa.Table.from_pydict(rows, schema=frames_schema()), frames_path, compression="zstd")

    # map: the current map plus any unmerged segments (each in its own coordinate frame)
    maps = [(len(m.segments), m.map)] + [(i, s.map) for i, s in enumerate(m.segments)]
    mrows: dict[str, list] = {k: [] for k in maps_schema().names}
    for seg_id, vm in maps:
        p, c = vm.points(2)
        mrows["session_id"] += [sid] * len(p)
        mrows["segment"] += [seg_id] * len(p)
        mrows["x"] += p[:, 0].tolist(); mrows["y"] += p[:, 1].tolist(); mrows["z"] += p[:, 2].tolist()
        mrows["hits"] += c.astype(int).tolist()
    map_path = out / "maps" / f"{sid}.parquet"
    pq.write_table(pa.Table.from_pydict(mrows, schema=maps_schema()), map_path, compression="zstd")

    pts, _ = m.map.points(2)
    stats = {
        "frames": len(rows["seq"]), "app_sessions": app_session + 1, "duration_s": round(t1 - t0, 2),
        "status_counts": dict(statuses), "tracking_fraction": round(statuses["tracking"] / len(rows["seq"]), 3),
        "mean_valid_fraction": round(float(np.mean(rows["valid_fraction"])), 3),
        "map_voxels": len(m.map), "map_points": int(len(pts)), "unmerged_segments": len(m.segments),
        "relocalizations": m.relocalizations, "merges": m.merges, "floor": floor_check(pts),
        "extent_m": [round(float(v), 2) for v in (np.ptp(pts, axis=0) if len(pts) else np.zeros(3))],
    }
    session = {
        "session_id": sid, "export_version": EXPORT_VERSION, "protocol_version": protocol.VERSION,
        "mapper_version": __version__, "source_file": esd.name, "exported_at": datetime.now(timezone.utc).isoformat(),
        "recorded_at": datetime.fromtimestamp(esd.stat().st_mtime, timezone.utc).isoformat(),
        "labels": labels or {}, "notes": notes, "mapper_settings": {
            "voxel": m.map.voxel, "icp_voxel": m.icp_voxel, "max_range": m.max_range, "map_max_range": m.map_max_range,
            "edge_filter": m.edge_filter, "min_inlier_frac": m.min_inlier_frac, "pose_source": m.pose_source},
        "stats": stats,
    }
    session_path = out / "sessions" / f"{sid}.json"
    session_path.write_text(json.dumps(session, indent=2))
    return ExportResult(sid, frames_path, map_path, session_path, stats)


def upload(export: ExportResult, volume_dir: str, profile: str | None = None) -> list[str]:
    """Copy the three files into <volume_dir>/{frames,maps,sessions}/ with the Databricks CLI."""
    done = []
    for sub, path in (("frames", export.frames_path), ("maps", export.map_path), ("sessions", export.session_path)):
        dest = f"dbfs:{volume_dir.rstrip('/')}/{sub}/{path.name}"
        cmd = ["databricks", "fs", "cp", "--overwrite", str(path), dest] + (["--profile", profile] if profile else [])
        res = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ})
        if res.returncode != 0:
            raise RuntimeError(f"upload failed for {path.name}: {res.stderr.strip() or res.stdout.strip()}")
        done.append(dest)
    return done
