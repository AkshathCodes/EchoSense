"""Train a deep cluster classifier. UNTESTED until torch is installed.

    python -m sonar_perception train --data ../data/synthetic/v0 --model bev
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from . import views
from .dataset import load_clusters, split_by_scene
from .sim import CLASSES


def build_inputs(model: str, points: np.ndarray, rng: np.random.Generator, n_points: int = 256) -> np.ndarray:
    if model == "pointnet":
        return np.stack([views.pointset(p, n_points, rng).T for p in points])  # [M, 5, N]
    if model == "bev":
        return np.stack([views.bev(p) for p in points])
    if model == "voxel":
        return np.stack([views.voxels(p) for p in points])
    raise ValueError(model)


def train(
    data_dir: str | Path,
    model: str = "bev",
    epochs: int = 30,
    batch_size: int = 64,
    lr: float = 1e-3,
    seed: int = 0,
    out_dir: str | Path = "runs",
    device: str | None = None,
) -> dict:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset

    from .models.encoders import ClusterClassifier, make_encoder

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    device = device or ("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")

    d = load_clusters(data_dir)
    X = build_inputs(model, d["points"], rng)
    y = d["labels"].astype(np.int64)
    # 3-way split BY SCENE: test is the same split the RF baseline uses (same seed);
    # validation is carved out of the training scenes and used for epoch selection.
    # (2026-11-14: an earlier version selected the epoch on the test set -> optimistic.)
    tr, te = split_by_scene(d["scene_ids"], 0.2, seed)
    tr_idx = np.flatnonzero(tr)
    sub_tr, sub_va = split_by_scene(d["scene_ids"][tr_idx], 0.15, seed + 1)
    va = np.zeros_like(tr)
    va[tr_idx[sub_va]] = True
    tr = tr & ~va
    n_classes = len(CLASSES)

    counts = np.bincount(y[tr], minlength=n_classes).astype(np.float32)
    weights = np.where(counts > 0, counts.sum() / np.maximum(counts, 1) / n_classes, 0.0)

    train_dl = DataLoader(TensorDataset(torch.from_numpy(X[tr]), torch.from_numpy(y[tr])), batch_size=batch_size, shuffle=True)

    def predict(mask: np.ndarray) -> np.ndarray:
        net.eval()
        out = []
        with torch.no_grad():
            for (xb,) in DataLoader(TensorDataset(torch.from_numpy(X[mask])), batch_size=256):
                out.append(net(xb.to(device)).argmax(1).cpu().numpy())
        return np.concatenate(out) if out else np.zeros(0, np.int64)

    net = ClusterClassifier(make_encoder(model), n_classes).to(device)
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=1e-4)
    loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(weights, dtype=torch.float32, device=device))

    run = Path(out_dir) / f"{model}-s{seed}-{time.strftime('%Y%m%d-%H%M%S')}"
    run.mkdir(parents=True, exist_ok=True)
    (run / "config.json").write_text(
        json.dumps({"model": model, "n_points": int(d["points"].shape[1]), "n_classes": n_classes, "data": str(data_dir), "seed": seed, "epochs": epochs, "lr": lr})
    )
    best_val, best_ep, history = -1.0, -1, []
    for ep in range(epochs):
        net.train()
        total = 0.0
        for xb, yb in train_dl:
            xb, yb = xb.to(device), yb.to(device)
            if model == "pointnet":
                xb = xb + 0.01 * torch.randn_like(xb)  # light jitter augmentation
            opt.zero_grad()
            loss = loss_fn(net(xb), yb)
            loss.backward()
            opt.step()
            total += float(loss) * len(yb)
        val_acc = float((predict(va) == y[va]).mean())
        history.append({"epoch": ep, "train_loss": total / max(1, tr.sum()), "val_acc": val_acc})
        print(f"epoch {ep:3d}  loss {history[-1]['train_loss']:.4f}  val acc {val_acc:.3f}")
        if val_acc >= best_val:
            best_val, best_ep = val_acc, ep
            torch.save(net.state_dict(), run / "best.pt")

    # final test evaluation at the best-validation epoch only
    net.load_state_dict(torch.load(run / "best.pt", map_location=device))
    pred = predict(te)
    env_te = d["env"][te]
    test_acc = float((pred == y[te]).mean())
    per_env = {str(e): float((pred[env_te == e] == y[te][env_te == e]).mean()) for e in np.unique(env_te)}
    per_class_recall = {
        CLASSES[c]: float((pred[y[te] == c] == c).mean()) for c in range(n_classes) if (y[te] == c).any()
    }
    metrics = {
        "model": model, "data": str(data_dir), "seed": seed,
        "n_train": int(tr.sum()), "n_val": int(va.sum()), "n_test": int(te.sum()),
        "best_epoch": best_ep, "val_acc": best_val, "test_acc": test_acc,
        "per_env_test_acc": per_env, "per_class_test_recall": per_class_recall, "history": history,
    }
    (run / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"best val acc {best_val:.3f} @ epoch {best_ep}; TEST acc {test_acc:.3f}; saved to {run}")
    return metrics
