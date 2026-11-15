"""CLI: python -m sonar_perception {generate,baseline,train,compare,detect,diagnose,view} ...

Sensing options shared by generate / detect (--synthetic) / diagnose:
  --tilt DEG            sensor pitched down
  --pings N             pings averaged per frame (noise / sqrt(N))
  --sweep N             fuse N poses as the wearer sweeps side to side
  --sweep-yaw DEG       total yaw span of the sweep (default 40)
  --sweep-step M        forward travel across the sweep (default 0)
A model should be evaluated with the same sensing options it was trained with.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _add_sensing(p: argparse.ArgumentParser) -> None:
    p.add_argument("--tilt", type=float, default=0.0, help="sensor pitched down by this many degrees")
    p.add_argument("--pings", type=int, default=1, help="pings averaged per frame")
    p.add_argument("--sweep", type=int, default=1, help="number of sweep poses fused (1 = single view)")
    p.add_argument("--sweep-yaw", type=float, default=40.0, help="total sweep yaw span, degrees")
    p.add_argument("--sweep-step", type=float, default=0.0, help="forward travel across the sweep, meters")
    p.add_argument("--min-views", type=int, default=1, help="sweep fusion: keep voxels seen from at least this many poses")


def _sensing(a):
    from dataclasses import replace

    from .config import SensorConfig, SweepConfig

    sensor = replace(SensorConfig(), tilt_deg=a.tilt, pings_averaged=a.pings)
    sweep = SweepConfig(n_poses=a.sweep, yaw_span_deg=a.sweep_yaw if a.sweep > 1 else 0.0, step_m=a.sweep_step, min_views=a.min_views)
    return sensor, sweep


def _env(name: str):
    from .config import EnvironmentConfig

    return None if name == "random" else EnvironmentConfig.preset(name)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="sonar_perception")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="simulate scenes and build a cluster dataset")
    g.add_argument("--scenes", type=int, default=300)
    g.add_argument("--out", required=True)
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--env", default="random", help="random | clear | fog | warm | heavy | extreme (held out)")
    g.add_argument("--no-frames", action="store_true", help="skip saving per-scene SonarFrames")
    g.add_argument("--diversity", choices=["off", "train", "challenge"], default="off",
                   help="opt-in uncalibrated acquisition diversity; defaults preserve existing data")
    _add_sensing(g)

    b = sub.add_parser("baseline", help="random forest on cluster features (no torch)")
    b.add_argument("--data", required=True)
    b.add_argument("--seed", type=int, default=0)

    t = sub.add_parser("train", help="train a deep cluster classifier (needs torch)")
    t.add_argument("--data", required=True)
    t.add_argument("--model", default="bev", choices=["pointnet", "bev", "voxel"])
    t.add_argument("--epochs", type=int, default=30)
    t.add_argument("--out", default="runs")

    c = sub.add_parser("compare", help="RF + deep models over several seeds (deep models need torch)")
    c.add_argument("--data", required=True)
    c.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    c.add_argument("--models", nargs="*", default=["bev", "pointnet", "voxel"])
    c.add_argument("--epochs", type=int, default=40)
    c.add_argument("--out", default="runs")

    dt = sub.add_parser("detect", help="run a trained classifier on frames and write detections JSON")
    dt.add_argument("--model", required=True, help="baseline_rf.joblib or a torch run dir")
    src = dt.add_mutually_exclusive_group(required=True)
    src.add_argument("--source", help="folder of SonarFrame .npz files")
    src.add_argument("--synthetic", type=int, help="simulate N fresh frames instead")
    dt.add_argument("--seed", type=int, default=12345, help="seed for --synthetic (keep different from training seeds)")
    dt.add_argument("--env", default="random", help="conditions for --synthetic")
    dt.add_argument("--out", default=None, help="folder for detections_*.json + summary.json")
    dt.add_argument("--include-noise", action="store_true")
    dt.add_argument("--bias", nargs="*", default=None, help="cost-sensitive factors, e.g. person=2")
    _add_sensing(dt)

    dg = sub.add_parser("diagnose", help="where are objects of one class lost? (fresh synthetic scenes)")
    dg.add_argument("--model", required=True)
    dg.add_argument("--class", dest="cls", default="person")
    dg.add_argument("--scenes", type=int, default=300)
    dg.add_argument("--seed", type=int, default=4242)
    dg.add_argument("--env", default="random")
    dg.add_argument("--out", default=None, help="write summary JSON here")
    dg.add_argument("--bias", nargs="*", default=None, help="cost-sensitive factors, e.g. person=2")
    _add_sensing(dg)

    v = sub.add_parser("view", help="plot one saved scene")
    v.add_argument("--data", required=True)
    v.add_argument("--scene", type=int, default=0)
    v.add_argument("--color", default="label", choices=["label", "cluster", "intensity"])
    v.add_argument("--out", default=None, help="save PNG instead of opening a window")

    a = ap.parse_args(argv)
    if a.cmd == "generate":
        from .dataset import generate

        sensor, sweep = _sensing(a)
        from .augmentation import AcquisitionDiversity
        diversity = None if a.diversity == "off" else AcquisitionDiversity.challenge() if a.diversity == "challenge" else AcquisitionDiversity()
        m = generate(a.out, a.scenes, seed=a.seed, env_mode=a.env, save_frames=not a.no_frames, sensor=sensor, sweep=sweep, diversity=diversity)
        print(json.dumps({k: m[k] for k in ("n_scenes", "n_clusters", "class_counts", "mean_purity")}, indent=2))
    elif a.cmd == "baseline":
        from .baseline import run_baseline

        run_baseline(a.data, seed=a.seed)
    elif a.cmd == "train":
        try:
            import torch  # noqa: F401
        except ImportError:
            raise SystemExit('PyTorch not installed. Run: pip install -e ".[torch]"')
        from .train import train

        train(a.data, model=a.model, epochs=a.epochs, out_dir=a.out)
    elif a.cmd == "compare":
        from .compare import compare

        compare(a.data, a.seeds, a.models, epochs=a.epochs, out_dir=a.out)
    elif a.cmd == "detect":
        from .inference import load_classifier, parse_bias, run_detect
        from .sources import RecordedSource, SyntheticSource

        if a.source:
            frames = RecordedSource(a.source)
        else:
            sensor, sweep = _sensing(a)
            frames = SyntheticSource(n_frames=a.synthetic, seed=a.seed, env=_env(a.env), sensor=sensor, sweep=sweep)
        run_detect(frames, load_classifier(a.model, parse_bias(a.bias)), a.out, include_noise=a.include_noise)
    elif a.cmd == "diagnose":
        from .diagnostics import object_outcomes, print_summary, summarize
        from .inference import load_classifier, parse_bias
        from .sources import SyntheticSource

        sensor, sweep = _sensing(a)
        src_ = SyntheticSource(n_frames=a.scenes, seed=a.seed, env=_env(a.env), sensor=sensor, sweep=sweep)
        summ = summarize(object_outcomes(src_, load_classifier(a.model, parse_bias(a.bias)), a.cls))
        print_summary(summ)
        if a.out:
            Path(a.out).write_text(json.dumps(summ, indent=2))
    elif a.cmd == "view":
        from .frame import SonarFrame
        from .segmentation import cluster_points
        from .viz import plot_frame

        frame = SonarFrame.load(Path(a.data) / "scenes" / f"scene_{a.scene:05d}.npz")
        ids = cluster_points(frame.points) if a.color == "cluster" else None
        plot_frame(frame, color_by=a.color, cluster_ids=ids, out=a.out)
        if a.out:
            print(f"saved {a.out}")


if __name__ == "__main__":
    main()
