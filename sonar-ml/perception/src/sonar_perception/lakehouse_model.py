"""MLflow pyfunc wrapper for the cluster classifier (ADR-0014).

Input: a DataFrame with the 26 `features.FEATURE_NAMES` columns (one row per
cluster). Output: `class`, `confidence`, and one `p_<class>` column per class,
with the person bias (ADR-0012) already applied, so a Model Serving endpoint
and batch scoring give the same answer as `detect --bias person=2`.

Only this module imports mlflow; the rest of the package doesn't need it.
"""

from __future__ import annotations

import json

import numpy as np

from .features import FEATURE_NAMES
from .lakehouse import CLASS_NAMES, FeatureForest

try:
    import mlflow.pyfunc

    _Base = mlflow.pyfunc.PythonModel
except ImportError:  # local use without mlflow
    _Base = object


def predictions_frame(model: FeatureForest, features):
    import pandas as pd

    X = features[FEATURE_NAMES].to_numpy(float) if hasattr(features, "columns") else np.asarray(features, float)
    p = model.predict_proba_features(X)
    k = p.argmax(axis=1) if len(p) else np.zeros(0, int)
    out = pd.DataFrame({"class": [CLASS_NAMES[i] for i in k], "confidence": p.max(axis=1) if len(p) else []})
    for i, name in enumerate(CLASS_NAMES):
        out[f"p_{name}"] = p[:, i] if len(p) else []
    return out


class SonarClusterClassifier(_Base):
    """Artifacts: `forest` (joblib RandomForestClassifier), `bias` (JSON dict)."""

    def load_context(self, context) -> None:
        import joblib

        forest = joblib.load(context.artifacts["forest"])
        with open(context.artifacts["bias"]) as f:
            bias = json.load(f)
        self.model = FeatureForest(forest, bias)

    def predict(self, context, model_input, params=None):
        return predictions_frame(self.model, model_input)


def load_feature_forest(local_dir: str) -> FeatureForest:
    """Rebuild a FeatureForest from a downloaded MLflow model directory (no mlflow import needed).

    Searches for `forest.joblib` + `bias.json` anywhere below `local_dir` (MLflow
    keeps pyfunc artifacts in an `artifacts/` subfolder).
    """
    import os

    import joblib

    for d, _, files in os.walk(local_dir):
        if "forest.joblib" in files and "bias.json" in files:
            forest = joblib.load(os.path.join(d, "forest.joblib"))
            with open(os.path.join(d, "bias.json")) as f:
                bias = json.load(f)
            return FeatureForest(forest, bias)
    raise FileNotFoundError(f"forest.joblib / bias.json not found under {local_dir}")
