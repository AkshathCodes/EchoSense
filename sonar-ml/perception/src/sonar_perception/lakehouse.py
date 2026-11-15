"""Lakehouse adapters: SonarFrames <-> table rows, plus Spark-ready partition functions.

Used by the Databricks pipeline in `sonar-ml/databricks/` (ADR-0014), but has no
Spark or Databricks dependency itself: every function takes and returns plain
Python / numpy / pandas objects, so it is unit-tested locally.

Tables (Unity Catalog, `<catalog>.<schema>.*`):

  landing_frames / bronze_frames   one row per SonarFrame        FRAME_SCHEMA
  silver_clusters                  one row per segmented cluster CLUSTER_SCHEMA
  silver_objects                   ground-truth objects (sim)    OBJECT_SCHEMA
  gold_detections                  model output per cluster      DETECTION_SCHEMA
  gold_object_outcomes             end-to-end fate of each GT object (diagnose) OUTCOME_SCHEMA

The intensity volume is NOT stored in the tables (it is ~0.8 MB per frame and
nothing downstream of point extraction reads it); see ADR-0014.
"""

from __future__ import annotations

import io
import json
import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace

import numpy as np

from .config import EnvironmentConfig, SensorConfig, SimConfig, SweepConfig
from .features import FEATURE_NAMES, cluster_features
from .frame import FORMAT_VERSION, SonarFrame, SphericalGrid
from .segmentation import extract_clusters
from .sim import CLASSES, OBJECT_CLASSES, random_scene
from .sources.synthetic import simulate_sweep

N_CLASSES = len(CLASSES)
CLASS_NAMES = [CLASSES[i] for i in range(N_CLASSES)]

# ---------------------------------------------------------------- schemas (Spark DDL)

FRAME_SCHEMA = (
    "frame_id STRING, run_id STRING, scene_id INT, timestamp DOUBLE, source STRING, sensor_id STRING, "
    "format_version STRING, conditions STRING, temperature_c DOUBLE, tilt_deg DOUBLE, n_points INT, "
    "points ARRAY<ARRAY<FLOAT>>, point_labels ARRAY<INT>, point_instances ARRAY<INT>, "
    "range_edges ARRAY<DOUBLE>, az_edges ARRAY<DOUBLE>, el_edges ARRAY<DOUBLE>, meta_json STRING, "
    "sensing_json STRING"
)

CLUSTER_SCHEMA = (
    "frame_id STRING, run_id STRING, scene_id INT, conditions STRING, cluster_idx INT, n_points INT, "
    "centroid_x DOUBLE, centroid_y DOUBLE, centroid_z DOUBLE, range_m DOUBLE, azimuth_deg DOUBLE, "
    "elevation_deg DOUBLE, mean_intensity DOUBLE, features ARRAY<DOUBLE>, label INT, label_name STRING, "
    "purity DOUBLE, instance INT"
)

OBJECT_SCHEMA = (
    "frame_id STRING, run_id STRING, scene_id INT, conditions STRING, instance INT, name STRING, "
    "class_id INT, class_name STRING, variant STRING, x DOUBLE, y DOUBLE, range_m DOUBLE, n_points INT"
)

DETECTION_SCHEMA = (
    "frame_id STRING, run_id STRING, scene_id INT, conditions STRING, model STRING, detection_id INT, "
    "class_name STRING, confidence DOUBLE, probs_json STRING, centroid_x DOUBLE, centroid_y DOUBLE, "
    "centroid_z DOUBLE, range_m DOUBLE, azimuth_deg DOUBLE, elevation_deg DOUBLE, n_points INT, "
    "mean_intensity DOUBLE, gt_class STRING"
)

OUTCOME_SCHEMA = (
    "frame_id STRING, run_id STRING, scene_id INT, conditions STRING, model STRING, class_name STRING, "
    "variant STRING, range_m DOUBLE, n_points INT, outcome STRING"
)


def schema_columns(ddl: str) -> list[str]:
    """Column names of a flat-or-nested DDL string (top-level only)."""
    cols, depth, tok = [], 0, ""
    for ch in ddl + ",":
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            cols.append(tok.strip().split()[0])
            tok = ""
        else:
            tok += ch
    return cols


# ---------------------------------------------------------------- sensing settings

RECOMMENDED_SENSING = {"pings": 4, "tilt": 0.0, "sweep": 1, "sweep_yaw": 40.0, "sweep_step": 0.0, "min_views": 1}


def make_sensing(sensing: dict | None = None) -> tuple[SensorConfig, SweepConfig]:
    """Same mapping as the CLI flags (--pings, --tilt, --sweep, ...)."""
    s = {**RECOMMENDED_SENSING, **(sensing or {})}
    sensor = replace(SensorConfig(), tilt_deg=float(s["tilt"]), pings_averaged=int(s["pings"]))
    n = int(s["sweep"])
    sweep = SweepConfig(n_poses=n, yaw_span_deg=float(s["sweep_yaw"]) if n > 1 else 0.0,
                        step_m=float(s["sweep_step"]), min_views=int(s["min_views"]))
    return sensor, sweep


def simulate_scene(seed: int, index: int, env_mode: str = "random", sensing: dict | None = None,
                   threshold_jitter: bool = True, sim: SimConfig | None = None) -> SonarFrame:
    """One labeled synthetic frame. Same RNG stream as `dataset.generate(seed=seed)` scene `index`."""
    sensor, sweep = make_sensing(sensing)
    sim = sim or SimConfig()
    rng = np.random.default_rng([seed, index])
    env = EnvironmentConfig.random(rng) if env_mode == "random" else EnvironmentConfig.preset(env_mode)
    scene_sensor = sensor
    if threshold_jitter:
        scene_sensor = replace(sensor, point_threshold_db=float(rng.uniform(-55, -45)),
                               noise_margin_db=float(rng.uniform(10, 18)))
    scene = random_scene(rng, sim, sensor)
    return simulate_sweep(scene, scene_sensor, env, sim, sweep, rng, timestamp=float(index), scene_id=index)


# ---------------------------------------------------------------- frame <-> row

def _conditions(meta: dict) -> str | None:
    c = meta.get("conditions")
    if isinstance(c, dict):
        return c.get("name")
    return c


def frame_to_row(frame: SonarFrame, frame_id: str, run_id: str, sensing: dict | None = None) -> dict:
    m = frame.meta
    n = len(frame.points)
    labels = frame.point_labels if frame.point_labels is not None else None
    insts = frame.point_instances if frame.point_instances is not None else None
    scene_id = m.get("scene_id")
    return {
        "frame_id": frame_id,
        "run_id": run_id,
        "scene_id": int(scene_id) if scene_id is not None else None,
        "timestamp": float(frame.timestamp),
        "source": m.get("source"),
        "sensor_id": m.get("sensor_id"),
        "format_version": str(m.get("format_version", FORMAT_VERSION)),
        "conditions": _conditions(m),
        "temperature_c": float(m["temperature_c"]) if m.get("temperature_c") is not None else None,
        "tilt_deg": float(m.get("tilt_deg", 0.0)),
        "n_points": int(n),
        "points": frame.points.astype(np.float32).tolist(),
        "point_labels": labels.astype(int).tolist() if labels is not None else None,
        "point_instances": insts.astype(int).tolist() if insts is not None else None,
        "range_edges": frame.grid.range_edges.astype(float).tolist(),
        "az_edges": frame.grid.az_edges.astype(float).tolist(),
        "el_edges": frame.grid.el_edges.astype(float).tolist(),
        "meta_json": json.dumps(m),
        "sensing_json": json.dumps(sensing) if sensing is not None else None,
    }


def _seq(v):
    """Arrow/pandas hand nested lists back as numpy object arrays; normalize to a list (or None)."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return list(v)


def row_to_frame(row) -> SonarFrame:
    """Rebuild a SonarFrame from a table row (volume is zero-filled: it isn't stored)."""
    grid = SphericalGrid(np.asarray(_seq(row["range_edges"]), float), np.asarray(_seq(row["az_edges"]), float),
                         np.asarray(_seq(row["el_edges"]), float))
    pts = _seq(row["points"]) or []
    points = np.asarray([list(p) for p in pts], np.float32).reshape(-1, 4)
    labels, insts = _seq(row["point_labels"]), _seq(row["point_instances"])
    meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
    meta["volume_stored"] = False
    return SonarFrame(
        timestamp=float(row["timestamp"]),
        grid=grid,
        volume=np.zeros(grid.shape, np.float32),
        points=points,
        meta=meta,
        point_labels=np.asarray(labels, np.int16) if labels is not None else None,
        point_instances=np.asarray(insts, np.int32) if insts is not None else None,
    )


def npz_to_row(content: bytes, path: str, run_id: str = "landing") -> dict:
    """A `.npz` SonarFrame file (recorded or live capture dropped into the landing volume) -> frame row."""
    frame = SonarFrame.load(io.BytesIO(content))
    return frame_to_row(frame, frame_id=path, run_id=run_id)


# ---------------------------------------------------------------- clusters, objects

def _geometry(points: np.ndarray) -> dict:
    c = points[:, :3].astype(np.float64).mean(axis=0)
    r = float(np.linalg.norm(c))
    return {
        "centroid_x": float(c[0]), "centroid_y": float(c[1]), "centroid_z": float(c[2]), "range_m": r,
        "azimuth_deg": math.degrees(math.atan2(c[1], c[0])),
        "elevation_deg": math.degrees(math.asin(float(np.clip(c[2] / max(r, 1e-9), -1, 1)))),
        "mean_intensity": float(points[:, 3].mean()),
    }


def cluster_rows(frame: SonarFrame, frame_id: str, run_id: str) -> list[dict]:
    clusters, _ = extract_clusters(frame)
    base = {"frame_id": frame_id, "run_id": run_id, "scene_id": frame.meta.get("scene_id"),
            "conditions": _conditions(frame.meta)}
    rows = []
    for i, c in enumerate(clusters):
        label = int(c.label)
        rows.append({
            **base, "cluster_idx": i, "n_points": int(len(c.points)), **_geometry(c.points),
            "features": cluster_features(c.points).astype(float).tolist(),
            "label": label if label >= 0 else None,
            "label_name": CLASSES[label] if label >= 0 else None,
            "purity": float(c.purity) if not math.isnan(c.purity) else None,
            "instance": int(c.instance),
        })
    return rows


def object_rows(frame: SonarFrame, frame_id: str, run_id: str) -> list[dict]:
    """Ground-truth objects (synthetic frames only) with how many points each produced."""
    objs = frame.meta.get("object_list") or []
    rows = []
    for o in objs:
        n = int((frame.point_instances == o["instance"]).sum()) if frame.point_instances is not None else None
        rows.append({
            "frame_id": frame_id, "run_id": run_id, "scene_id": frame.meta.get("scene_id"),
            "conditions": _conditions(frame.meta), "instance": int(o["instance"]), "name": o["name"],
            "class_id": int(o["class_id"]), "class_name": CLASSES[int(o["class_id"])],
            "variant": o.get("variant", ""), "x": float(o["x"]), "y": float(o["y"]),
            "range_m": float(math.hypot(o["x"], o["y"])), "n_points": n,
        })
    return rows


# ---------------------------------------------------------------- classifier on stored features

@dataclass
class FeatureForest:
    """Random forest over the 26 cluster features + optional per-class bias (ADR-0012).

    Works both on precomputed feature rows (`predict_proba_features`, what the
    lakehouse and the serving endpoint use) and on raw cluster point arrays
    (`predict_proba`, the interface `inference.detect_frame` / `diagnostics` expect).
    """

    forest: object
    bias: dict[str, float]
    name: str = "random_forest_features"

    def factors(self) -> np.ndarray:
        f = np.ones(N_CLASSES)
        for k, v in self.bias.items():
            f[CLASS_NAMES.index(k)] = v
        return f

    def predict_proba_features(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, float).reshape(-1, len(FEATURE_NAMES))
        if len(X) == 0:
            return np.zeros((0, N_CLASSES))
        out = np.zeros((len(X), N_CLASSES))
        out[:, self.forest.classes_.astype(int)] = self.forest.predict_proba(X)
        out *= self.factors()
        return out / np.maximum(out.sum(axis=1, keepdims=True), 1e-12)

    def predict_proba(self, clusters: list[np.ndarray]) -> np.ndarray:
        if not clusters:
            return np.zeros((0, N_CLASSES))
        return self.predict_proba_features(np.stack([cluster_features(p) for p in clusters]))

    @property
    def full_name(self) -> str:
        if not self.bias:
            return self.name
        return self.name + "+bias(" + ",".join(f"{k}={v:g}" for k, v in self.bias.items()) + ")"


def scene_split(scene_keys: np.ndarray, test_frac: float = 0.2, seed: int = 0) -> np.ndarray:
    """Boolean test mask, assigned per scene key (never splits a scene)."""
    keys = np.unique(scene_keys)
    rng = np.random.default_rng(seed)
    test_keys = rng.choice(keys, max(1, int(round(len(keys) * test_frac))), replace=False)
    return np.isin(scene_keys, test_keys)


def train_forest(features: np.ndarray, labels: np.ndarray, scene_keys: np.ndarray,
                 conditions: np.ndarray | None = None, seed: int = 0, test_frac: float = 0.2,
                 n_estimators: int = 300, bias: dict[str, float] | None = None) -> tuple[FeatureForest, dict, np.ndarray]:
    """Same model as `baseline.run_baseline`, on table rows. Returns (model, metrics, test_mask)."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support

    X = np.asarray(features, float)
    y = np.asarray(labels, int)
    te = scene_split(np.asarray(scene_keys), test_frac, seed)
    forest = RandomForestClassifier(n_estimators=n_estimators, class_weight="balanced", random_state=seed, n_jobs=-1)
    forest.fit(X[~te], y[~te])
    model = FeatureForest(forest, dict(bias or {}))
    pred = model.predict_proba_features(X[te]).argmax(axis=1)
    present = sorted(int(c) for c in np.unique(y))
    p, r, f, s = precision_recall_fscore_support(y[te], pred, labels=present, zero_division=0)
    metrics = {
        "n_train": int((~te).sum()), "n_test": int(te.sum()),
        "accuracy": float(accuracy_score(y[te], pred)),
        **{f"precision_{CLASSES[c]}": float(v) for c, v in zip(present, p)},
        **{f"recall_{CLASSES[c]}": float(v) for c, v in zip(present, r)},
    }
    if conditions is not None:
        cond = np.asarray(conditions)[te]
        for e in np.unique(cond):
            metrics[f"accuracy_{e}"] = float(accuracy_score(y[te][cond == e], pred[cond == e]))
    metrics["_confusion"] = {"labels": [CLASSES[c] for c in present],
                             "matrix": confusion_matrix(y[te], pred, labels=present).tolist()}
    return model, metrics, te


# ---------------------------------------------------------------- scoring

def detection_rows(frame: SonarFrame, frame_id: str, run_id: str, model: FeatureForest) -> list[dict]:
    from .inference import detect_frame

    dets, _ = detect_frame(frame, model)
    base = {"frame_id": frame_id, "run_id": run_id, "scene_id": frame.meta.get("scene_id"),
            "conditions": _conditions(frame.meta), "model": model.full_name}
    return [{
        **base, "detection_id": d.id, "class_name": d.class_name, "confidence": d.confidence,
        "probs_json": json.dumps(d.probs), "centroid_x": d.centroid[0], "centroid_y": d.centroid[1],
        "centroid_z": d.centroid[2], "range_m": d.range_m, "azimuth_deg": d.azimuth_deg,
        "elevation_deg": d.elevation_deg, "n_points": d.n_points, "mean_intensity": d.mean_intensity,
        "gt_class": d.gt_class,
    } for d in dets]


def outcome_rows(frame: SonarFrame, frame_id: str, run_id: str, model: FeatureForest) -> list[dict]:
    """End-to-end fate of every ground-truth object (invisible / merged / fragmented / wrong:X / correct)."""
    from .diagnostics import object_outcomes

    base = {"frame_id": frame_id, "run_id": run_id, "scene_id": frame.meta.get("scene_id"),
            "conditions": _conditions(frame.meta), "model": model.full_name}
    # The floor is stored with the wall class id but labeled background (ADR-0010): not an object to find.
    objs = [o for o in frame.meta.get("object_list") or [] if o.get("name") != "floor"]
    frame = replace(frame, meta={**frame.meta, "object_list": objs})
    rows = []
    for cid in OBJECT_CLASSES:
        for o in object_outcomes([frame], model, CLASSES[cid]):
            rows.append({**base, "class_name": CLASSES[cid], "variant": o["variant"], "range_m": o["range"],
                         "n_points": o["n_points"], "outcome": o["outcome"]})
    return rows


# ---------------------------------------------------------------- Spark partition functions
# Each returns a function usable with DataFrame.mapInPandas(fn, schema=...).

def _frames_df(rows: list[dict], ddl: str):
    import pandas as pd

    return pd.DataFrame(rows, columns=schema_columns(ddl))


def generate_partitions(run_id: str, seed: int, env_mode: str = "random", sensing: dict | None = None,
                        threshold_jitter: bool = True) -> Callable[[Iterator], Iterator]:
    """Input rows: `scene_index` (int). Output: FRAME_SCHEMA rows (one simulated frame each)."""
    sensing = {**RECOMMENDED_SENSING, **(sensing or {})}

    def fn(batches):
        for pdf in batches:
            rows = []
            for idx in pdf["scene_index"].tolist():
                frame = simulate_scene(seed, int(idx), env_mode, sensing, threshold_jitter)
                rows.append(frame_to_row(frame, f"{run_id}-{int(idx):06d}", run_id, sensing))
            yield _frames_df(rows, FRAME_SCHEMA)

    return fn


def npz_partitions(run_id: str = "landing") -> Callable[[Iterator], Iterator]:
    """Input: Auto Loader binaryFile rows (`path`, `content`). Output: FRAME_SCHEMA rows."""

    def fn(batches):
        for pdf in batches:
            yield _frames_df([npz_to_row(bytes(c), p, run_id) for p, c in zip(pdf["path"], pdf["content"])],
                             FRAME_SCHEMA)

    return fn


def _per_frame(make_rows: Callable[[SonarFrame, str, str], list[dict]], ddl: str) -> Callable[[Iterator], Iterator]:
    def fn(batches):
        for pdf in batches:
            rows = []
            for _, r in pdf.iterrows():
                rows.extend(make_rows(row_to_frame(r), r["frame_id"], r["run_id"]))
            yield _frames_df(rows, ddl)

    return fn


def cluster_partitions():
    """FRAME_SCHEMA rows -> CLUSTER_SCHEMA rows."""
    return _per_frame(cluster_rows, CLUSTER_SCHEMA)


def object_partitions():
    """FRAME_SCHEMA rows -> OBJECT_SCHEMA rows (ground truth)."""
    return _per_frame(object_rows, OBJECT_SCHEMA)


def detection_partitions(model: FeatureForest):
    return _per_frame(lambda f, fid, rid: detection_rows(f, fid, rid, model), DETECTION_SCHEMA)


def outcome_partitions(model: FeatureForest):
    return _per_frame(lambda f, fid, rid: outcome_rows(f, fid, rid, model), OUTCOME_SCHEMA)
