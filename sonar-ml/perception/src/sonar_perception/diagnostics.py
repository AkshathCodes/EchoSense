"""Per-object failure analysis: where in the pipeline does each real object get lost?

    python -m sonar_perception diagnose --model ../data/synthetic/v2/baseline_rf.joblib --class person --scenes 300

For every ground-truth object of the chosen class in fresh synthetic scenes,
the outcome is one of:
  invisible      fewer than `min_points` points survive (occlusion, out of FOV, below noise)
  merged         its points mostly sit in a cluster dominated by another instance
  fragmented     visible but no cluster of its own (DBSCAN noise or clusters too small)
  correct        its cluster is predicted as the right class
  wrong:<class>  its cluster is predicted as another class
Outcomes are broken down by variant (e.g. person pose) and by range band.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

import numpy as np

from .segmentation import extract_clusters
from .sim.shapes import CLASS_IDS, CLASSES


def object_outcomes(frames, clf, class_name: str, min_points: int = 8) -> list[dict]:
    target = CLASS_IDS[class_name]
    rows = []
    for frame in frames:
        objs = frame.meta.get("object_list", [])
        clusters, ids = extract_clusters(frame)
        probs = clf.predict_proba([c.points for c in clusters]) if clusters else np.zeros((0, len(CLASSES)))
        preds = probs.argmax(axis=1) if len(probs) else np.zeros(0, int)
        by_inst = {c.instance: (c, int(p)) for c, p in zip(clusters, preds)}
        for o in objs:
            if o["class_id"] != target:
                continue
            inst = o["instance"]
            mask = frame.point_instances == inst
            n = int(mask.sum())
            row = {"variant": o.get("variant", ""), "range": float(np.hypot(o["x"], o["y"])), "n_points": n,
                   "conditions": (frame.meta.get("conditions") or {}).get("name")}
            if n < min_points:
                row["outcome"] = "invisible"
            elif inst in by_inst:
                p = by_inst[inst][1]
                row["outcome"] = "correct" if p == target else f"wrong:{CLASSES[p]}"
            else:
                cids = ids[mask]
                cids = cids[cids >= 0]
                row["outcome"] = "merged" if len(cids) and np.bincount(cids).max() >= 0.5 * n else "fragmented"
            rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    def dist(rs):
        c = Counter(r["outcome"] for r in rs)
        n = max(1, len(rs))
        return {"n": len(rs), **{k: round(v / n, 3) for k, v in c.most_common()}}

    by_variant = defaultdict(list)
    by_range = defaultdict(list)
    by_cond = defaultdict(list)
    for r in rows:
        by_variant[r["variant"] or "-"].append(r)
        by_range["<2m" if r["range"] < 2 else "2-4m" if r["range"] < 4 else ">4m"].append(r)
        by_cond[r["conditions"] or "-"].append(r)
    return {
        "overall": dist(rows),
        "by_variant": {k: dist(v) for k, v in sorted(by_variant.items())},
        "by_range": {k: dist(v) for k, v in sorted(by_range.items())},
        "by_conditions": {k: dist(v) for k, v in sorted(by_cond.items())},
    }


def print_summary(s: dict) -> None:
    print(json.dumps(s, indent=2))
