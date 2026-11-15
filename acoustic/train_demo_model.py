"""Train and evaluate the EchoSense demo forest, then export a sonar replay."""

import argparse
import json
from pathlib import Path
from collections.abc import Sequence
from typing import TypedDict

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score

from sonar_perception.config import SensorConfig
from sonar_perception.dataset import generate, load_clusters
from sonar_perception.diagnostics import object_outcomes, summarize
from sonar_perception.frame import SonarFrame
from sonar_perception.inference import BiasedClassifier, ForestClassifier, detect_frame, run_detect
from sonar_perception.sources import SyntheticSource


class ClusterScores(TypedDict):
    accuracy: float
    macro_f1: float


class DetectionScores(TypedDict):
    recall: float
    precision: float
    false_alarms: int
    f2: float


def scores(model: RandomForestClassifier, dataset: Path) -> ClusterScores:
    data = load_clusters(dataset)
    predicted = model.predict(data["features"])
    return {
        "accuracy": float(accuracy_score(data["labels"], predicted)),
        "macro_f1": float(f1_score(data["labels"], predicted, average="macro")),
    }


def detection_scores(
    frames: Sequence[SonarFrame], classifier: ForestClassifier | BiasedClassifier
) -> tuple[DetectionScores, dict]:
    rows = object_outcomes(frames, classifier, "person")
    correct = sum(row["outcome"] == "correct" for row in rows)
    recall = correct / len(rows)
    # A prediction that didn't contribute an object-level hit counts as a false alarm.
    predictions = 0
    for frame in frames:
        detections, _ = detect_frame(frame, classifier)
        predictions += sum(det.class_name == "person" for det in detections)
    false_alarms = predictions - correct
    precision = correct / predictions if predictions else 0
    f2 = 5 * precision * recall / (4 * precision + recall) if precision + recall else 0
    return {"recall": recall, "precision": precision, "false_alarms": false_alarms, "f2": f2}, summarize(rows)


def evaluate(output: Path, train_scenes: int, validation_scenes: int, test_scenes: int) -> None:
    output.mkdir(parents=True, exist_ok=True)
    train, validation, test = (output / name for name in ("train", "validation", "test"))
    sensor = SensorConfig(pings_averaged=4)
    for path, count, seed in ((train, train_scenes, 2718), (validation, validation_scenes, 3141),
                              (test, test_scenes, 5772)):
        print(f"Generating {path.name}: {count} synthetic scenes", flush=True)
        generate(path, n_scenes=count, seed=seed, n_points=64, save_frames=False, sensor=sensor)

    data = load_clusters(train)
    settings = {
        "Current forest": (300, None, 1, "balanced"),
        "Regularized forest": (300, None, 3, "balanced_subsample"),
        "Shallow forest": (300, 16, 2, "balanced_subsample"),
    }
    models: dict[str, RandomForestClassifier] = {}
    selection: dict[str, ClusterScores] = {}
    for name, (trees, depth, leaf, weights) in settings.items():
        clf = RandomForestClassifier(n_estimators=trees, max_depth=depth, min_samples_leaf=leaf,
                                     class_weight=weights, random_state=0, n_jobs=-1)
        clf.fit(data["features"], data["labels"])
        models[name] = clf
        selection[name] = scores(clf, validation)
        print(f"{name}: validation macro F1 {selection[name]['macro_f1']:.3f}", flush=True)

    selected = max(selection, key=lambda name: selection[name]["macro_f1"])
    selected_path = output / "echosense-rf.joblib"
    baseline_path = output / "baseline-rf.joblib"
    joblib.dump(models[selected], selected_path, compress=3)
    joblib.dump(models["Current forest"], baseline_path, compress=3)
    print(f"Selected {selected}. Tuning person-sized-object recall on validation scenes.", flush=True)
    model = ForestClassifier(selected_path)
    validation_frames = list(SyntheticSource(n_frames=validation_scenes, seed=2028, sensor=sensor))
    operating_points: dict[float, DetectionScores] = {}
    for factor in (1.0, 1.5, 2.0, 2.5, 3.0):
        score, _ = detection_scores(validation_frames, BiasedClassifier(model, {"person": factor}))
        operating_points[factor] = score
        print(f"Weight {factor:g}: recall {score['recall']:.3f}, precision {score['precision']:.3f}, F2 {score['f2']:.3f}", flush=True)
    weight = max(operating_points, key=lambda factor: operating_points[factor]["f2"])
    classifier = BiasedClassifier(model, {"person": weight})
    frames = list(SyntheticSource(n_frames=test_scenes, seed=8675, sensor=sensor))
    baseline = ForestClassifier(baseline_path)
    classifiers = {"baseline": baseline, "baseline_weighted": BiasedClassifier(baseline, {"person": 2.0}),
                   "selected": classifier}
    scene_results = {}
    for name, candidate in classifiers.items():
        score, breakdown = detection_scores(frames, candidate)
        scene_results[name] = {**score, "breakdown": breakdown}

    demo = output / "replay"
    frames = list(SyntheticSource(n_frames=8, seed=999, sensor=sensor))
    replay_summary = run_detect(frames, classifier, demo, verbose=False)
    entries = []
    for index, frame in enumerate(frames):
        filename = f"frame_{index:05d}.npz"
        frame.save(demo / filename)
        entries.append(json.dumps({"frame": filename, "detections": f"detections_{index:05d}.json"}))
    (demo / "manifest.jsonl").write_text("\n".join(entries) + "\n", encoding="utf-8")

    result = {
        "source": "simulated",
        "model": selected,
        "train_scenes": train_scenes,
        "validation_scenes": validation_scenes,
        "test_scenes": test_scenes,
        "training_seed": 2718,
        "validation_seed": 3141,
        "test_seed": 5772,
        "person_validation_seed": 2028,
        "person_test_seed": 8675,
        "pings": 4,
        "sklearn": sklearn.__version__,
        "numpy": np.__version__,
        "validation": selection,
        "person_weight": weight,
        "person_weight_validation": operating_points,
        "baseline": scores(models["Current forest"], test),
        "selected": scores(models[selected], test),
        "person_sized_object_test": scene_results,
        "replay": {"frames": replay_summary["n_frames"], "detections": replay_summary["n_detections"]},
    }
    (output / "model-evaluation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--train-scenes", type=int, required=True)
    parser.add_argument("--validation-scenes", type=int, required=True)
    parser.add_argument("--test-scenes", type=int, required=True)
    args = parser.parse_args()
    evaluate(args.output, args.train_scenes, args.validation_scenes, args.test_scenes)
