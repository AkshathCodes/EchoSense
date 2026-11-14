"""Baseline 0: random forest on hand-crafted cluster features. No torch needed."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from .dataset import load_clusters, split_by_scene
from .features import FEATURE_NAMES
from .sim import CLASSES


def run_baseline(
    data_dir: str | Path, seed: int = 0, test_frac: float = 0.2, verbose: bool = True, save_model: bool = True
) -> dict:
    """Train on a scene-split of `data_dir`, report test metrics, save the model as baseline_rf.joblib."""
    d = load_clusters(data_dir)
    X, y, env = d["features"], d["labels"], d["env"]
    tr, te = split_by_scene(d["scene_ids"], test_frac, seed)
    clf = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=seed, n_jobs=-1)
    clf.fit(X[tr], y[tr])
    pred = clf.predict(X[te])

    present = sorted(int(c) for c in np.unique(np.concatenate([y[tr], y[te]])))
    names = [CLASSES[c] for c in present]
    metrics = {
        "model": "random_forest_features",
        "data": str(data_dir),
        "n_train": int(tr.sum()),
        "n_test": int(te.sum()),
        "accuracy": float(accuracy_score(y[te], pred)),
        "per_env_accuracy": {
            str(e): float(accuracy_score(y[te][env[te] == e], pred[env[te] == e]))
            for e in np.unique(env[te])
        },
        "classes": names,
        "confusion_matrix": confusion_matrix(y[te], pred, labels=present).tolist(),
        "report": classification_report(y[te], pred, labels=present, target_names=names, output_dict=True, zero_division=0),
        "feature_importance": dict(
            sorted(zip(FEATURE_NAMES, clf.feature_importances_.round(4).tolist()), key=lambda kv: -kv[1])
        ),
    }
    if verbose:
        print(f"train clusters {metrics['n_train']}  test clusters {metrics['n_test']}  (split by scene)")
        print(f"accuracy {metrics['accuracy']:.3f}")
        print("per-environment accuracy:", {k: round(v, 3) for k, v in metrics["per_env_accuracy"].items()})
        print(classification_report(y[te], pred, labels=present, target_names=names, zero_division=0))
        print("confusion (rows=true, cols=pred):", names)
        for name, row in zip(names, metrics["confusion_matrix"]):
            print(f"  {name:>10} {row}")
    Path(data_dir, "baseline_metrics.json").write_text(json.dumps(metrics, indent=2))
    if save_model:
        import joblib

        joblib.dump(clf, Path(data_dir, "baseline_rf.joblib"))
    return metrics
