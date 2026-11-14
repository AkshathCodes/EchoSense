"""Compare the RF baseline and the deep models over several seeds (ADR-0007).

    python -m sonar_perception compare --data ../data/synthetic/v1 --seeds 0 1 2

Every seed changes the scene split, so the spread covers both split and
training randomness. For a given seed all models share the same TEST scenes.
The RF trains on train+val (it does no epoch selection); deep models hold out
15% of training scenes for validation and pick their epoch on it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .baseline import run_baseline


def compare(data_dir: str | Path, seeds: list[int], models: list[str], epochs: int = 40, out_dir: str | Path = "runs") -> dict:
    results: dict[str, list[dict]] = {"random_forest": []}
    for s in seeds:
        m = run_baseline(data_dir, seed=s, verbose=False, save_model=False)
        recall = {k: v["recall"] for k, v in m["report"].items() if k in m["classes"]}
        results["random_forest"].append({"test_acc": m["accuracy"], "per_env": m["per_env_accuracy"], "recall": recall})
    if models:
        from .train import train

        for name in models:
            results[name] = []
            for s in seeds:
                m = train(data_dir, model=name, epochs=epochs, seed=s, out_dir=out_dir)
                results[name].append({"test_acc": m["test_acc"], "per_env": m["per_env_test_acc"], "recall": m["per_class_test_recall"]})

    summary = {}
    for name, runs in results.items():
        accs = np.array([r["test_acc"] for r in runs])
        envs = sorted({e for r in runs for e in r["per_env"]})
        classes = sorted({c for r in runs for c in r["recall"]})
        summary[name] = {
            "test_acc_mean": float(accs.mean()),
            "test_acc_std": float(accs.std()),
            "per_env_mean": {e: float(np.mean([r["per_env"][e] for r in runs if e in r["per_env"]])) for e in envs},
            "recall_mean": {c: float(np.mean([r["recall"][c] for r in runs if c in r["recall"]])) for c in classes},
            "runs": runs,
        }
    out = {"data": str(data_dir), "seeds": seeds, "epochs": epochs, "summary": summary}
    Path(data_dir, "compare.json").write_text(json.dumps(out, indent=2))

    print(f"\n{'model':<14} {'test acc':>14}  " + "  ".join(f"{e:>6}" for e in ("clear", "fog", "warm", "heavy")) + "  person-recall  noise-recall")
    for name, sm in summary.items():
        env = sm["per_env_mean"]
        print(
            f"{name:<14} {sm['test_acc_mean']:.3f} ± {sm['test_acc_std']:.3f}  "
            + "  ".join(f"{env.get(e, float('nan')):6.3f}" for e in ("clear", "fog", "warm", "heavy"))
            + f"  {sm['recall_mean'].get('person', float('nan')):13.3f}  {sm['recall_mean'].get('noise', float('nan')):12.3f}"
        )
    return out
