"""Inference: any SonarFrame source -> clusters -> classifier -> detections.

    python -m sonar_perception detect --model ../data/synthetic/v1/baseline_rf.joblib \
        --source ../data/synthetic/v1-test/scenes --out ../data/detections/demo

Classifiers:
  - random forest: a `.joblib` written by `baseline` (no torch needed)
  - torch: a run directory written by `train` (contains config.json + best.pt)
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from .detections import Detection, frame_detections_dict
from .features import cluster_features
from .frame import SonarFrame
from .segmentation import extract_clusters
from .sim.shapes import CLASS_IDS, CLASSES, NOISE_CLASS

N_CLASSES = len(CLASSES)


class ForestClassifier:
    def __init__(self, path: str | Path) -> None:
        import joblib

        self.path = Path(path)
        self.clf = joblib.load(self.path)
        self.name = "random_forest_features"

    def predict_proba(self, clusters: list[np.ndarray]) -> np.ndarray:
        if not clusters:
            return np.zeros((0, N_CLASSES))
        X = np.stack([cluster_features(p) for p in clusters])
        proba = self.clf.predict_proba(X)
        out = np.zeros((len(clusters), N_CLASSES))
        out[:, self.clf.classes_.astype(int)] = proba
        return out


class TorchClassifier:
    def __init__(self, run_dir: str | Path, device: str = "cpu") -> None:
        import torch

        from .models.encoders import ClusterClassifier, make_encoder

        self.run_dir = Path(run_dir)
        cfg = json.loads((self.run_dir / "config.json").read_text())
        self.model_name, self.n_points = cfg["model"], cfg["n_points"]
        self.net = ClusterClassifier(make_encoder(self.model_name), cfg["n_classes"])
        self.net.load_state_dict(torch.load(self.run_dir / "best.pt", map_location=device))
        self.net.eval()
        self.device = device
        self.name = f"torch_{self.model_name}"

    def predict_proba(self, clusters: list[np.ndarray]) -> np.ndarray:
        import torch

        from .train import build_inputs

        if not clusters:
            return np.zeros((0, N_CLASSES))
        rng = np.random.default_rng(0)
        X = build_inputs(self.model_name, [p for p in clusters], rng, self.n_points)
        with torch.no_grad():
            logits = self.net(torch.from_numpy(X).to(self.device))
        return torch.softmax(logits, dim=1).cpu().numpy()


class BiasedClassifier:
    """Cost-sensitive decision rule: multiply class probabilities by per-class factors, renormalize.

    For firefighting a missed person costs far more than a false alarm, so
    e.g. {"person": 2.0} trades precision for recall (ADR-0012). The probabilities
    reported in detections are the re-weighted ones.
    """

    def __init__(self, base, bias: dict[str, float]) -> None:
        self.base = base
        self.factors = np.ones(N_CLASSES)
        for name, f in bias.items():
            self.factors[CLASS_IDS[name]] = f
        self.name = base.name + "+bias(" + ",".join(f"{k}={v:g}" for k, v in bias.items()) + ")"

    def predict_proba(self, clusters: list[np.ndarray]) -> np.ndarray:
        p = self.base.predict_proba(clusters) * self.factors
        return p / np.maximum(p.sum(axis=1, keepdims=True), 1e-12)


def parse_bias(items: list[str] | None) -> dict[str, float]:
    """['person=2', 'debris=0.8'] -> {'person': 2.0, 'debris': 0.8}"""
    out = {}
    for it in items or []:
        k, v = it.split("=")
        if k not in CLASS_IDS:
            raise ValueError(f"unknown class {k!r}")
        out[k] = float(v)
    return out


def load_classifier(path: str | Path, bias: dict[str, float] | None = None):
    p = Path(path)
    if p.is_dir() and (p / "best.pt").exists():
        clf = TorchClassifier(p)
    elif p.suffix == ".joblib":
        clf = ForestClassifier(p)
    else:
        raise ValueError(f"don't know how to load a classifier from {p}")
    return BiasedClassifier(clf, bias) if bias else clf


def detect_frame(frame: SonarFrame, clf, eps: float | None = None, min_samples: int = 4, include_noise: bool = False):
    """Returns (detections, list of (gt_label, pred_label) for labeled frames)."""
    clusters, _ = extract_clusters(frame, eps=eps, min_samples=min_samples)
    probs = clf.predict_proba([c.points for c in clusters])
    dets, pairs = [], []
    for c, p in zip(clusters, probs):
        pred = int(np.argmax(p))
        if frame.has_labels:
            pairs.append((c.label, pred))
        if pred == NOISE_CLASS and not include_noise:
            continue
        dets.append(Detection.from_cluster(0, c.points, p, c.label if frame.has_labels else None))
    dets.sort(key=lambda d: d.range_m)
    for i, d in enumerate(dets):
        d.id = i
    return dets, pairs


def run_detect(frames: Iterable[SonarFrame], clf, out_dir: str | Path | None = None, include_noise: bool = False, verbose: bool = True) -> dict:
    out = Path(out_dir) if out_dir else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    n_frames, n_dets, pairs = 0, 0, []
    for i, frame in enumerate(frames):
        dets, fp = detect_frame(frame, clf, include_noise=include_noise)
        pairs += fp
        n_frames += 1
        n_dets += len(dets)
        if out:
            (out / f"detections_{i:05d}.json").write_text(json.dumps(frame_detections_dict(frame, dets, clf.name), indent=2))
    summary: dict = {"model": clf.name, "n_frames": n_frames, "n_detections": n_dets}
    if pairs:
        gt, pr = np.array(pairs).T
        summary["cluster_accuracy_vs_gt"] = float((gt == pr).mean())
        obj = gt != NOISE_CLASS
        summary["object_recall"] = float((pr[obj] != NOISE_CLASS).mean()) if obj.any() else None
        summary["noise_rejection"] = float((pr[~obj] == NOISE_CLASS).mean()) if (~obj).any() else None
        summary["per_class"] = {
            CLASSES[k]: {
                "recall": float((pr[gt == k] == k).mean()) if (gt == k).any() else None,
                "precision": float((gt[pr == k] == k).mean()) if (pr == k).any() else None,
                "n_true": int((gt == k).sum()),
                "n_pred": int((pr == k).sum()),
            }
            for k in CLASSES
        }
    if out:
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
    if verbose:
        print(json.dumps(summary, indent=2))
    return summary
