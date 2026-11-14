# Databricks notebook source
# MAGIC %md
# MAGIC # EchoSense scan quality
# MAGIC Import acoustic trials, compare estimates with tape references, and export the map used by EchoSense.
# MAGIC Upload `sample-scans.csv` to a Unity Catalog volume for a simulated run, or upload the measured CSV from Acoustic Scan.
# MAGIC Set both widgets to full volume paths. A rejected pose leaves a gap in the resulting 3D view.

# COMMAND ----------

"""Aggregate EchoSense trials into a phone-readable map and accuracy report."""

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from html import escape
from pathlib import Path
from typing import Literal, NamedTuple, TextIO, TypedDict

Source = Literal["measured", "simulated"]


class Trial(NamedTuple):
    source: Source
    scene: str
    station_m: float
    reference_m: float | None
    status: str
    range_m: float | None
    pose: "Pose"


class Pose(NamedTuple):
    depth_m: float
    height_m: float
    heading_deg: float
    pitch_deg: float
    surface: str


class Point(TypedDict):
    scene: str
    station_m: float
    reference_m: float | None
    range_m: float | None
    spread_m: float | None
    error_m: float | None
    accepted: int
    total: int
    depth_m: float
    height_m: float
    heading_deg: float
    pitch_deg: float
    surface: str


class Report(TypedDict):
    source: Source
    points: list[Point]


class SceneQuality(TypedDict):
    scene: str
    poses: int
    mapped_poses: int
    coverage_pct: float
    trials: int
    usable_trials: int
    usable_trial_pct: float
    reference_poses: int
    mean_absolute_error_m: float | None
    max_absolute_error_m: float | None


def number(value: str, field: str, line: int) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"CSV line {line}: invalid {field} value {value!r}") from error
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"CSV line {line}: {field} must be finite and nonnegative")
    return parsed


def pose_value(row: dict[str, str | None], field: str, old_value: float,
               minimum: float, maximum: float, line: int) -> float:
    if field not in row:
        return old_value
    value = row[field]
    try:
        parsed = float(value) if value is not None else math.nan
    except ValueError as error:
        raise ValueError(f"CSV line {line}: invalid {field} value {value!r}") from error
    if not minimum <= parsed <= maximum:
        raise ValueError(f"CSV line {line}: {field} must be between {minimum:g} and {maximum:g}")
    return parsed


def read_trials(file: TextIO) -> list[Trial]:
    required = {"source", "scene", "station_m", "reference_m", "status", "range_m"}
    reader = csv.DictReader(file)
    missing = required.difference(reader.fieldnames or ())
    if missing:
        raise ValueError(f"Missing CSV columns {', '.join(sorted(missing))}")
    trials: list[Trial] = []
    for line, row in enumerate(reader, start=2):
        if any(row[key] is None for key in required):
            raise ValueError(f"CSV line {line} has missing values")
        source = row["source"]
        scene = row["scene"].strip()
        status = row["status"]
        if source not in ("measured", "simulated") or not scene:
            raise ValueError(f"CSV line {line}: specify a scene and measured or simulated source")
        if status not in ("ok", "no_direct", "no_echo", "ambiguous", "clipped"):
            raise ValueError(f"CSV line {line}: unrecognized scan status {status!r}")
        distance = number(row["range_m"], "range_m", line) if row["range_m"] else None
        if (status == "ok") != (distance is not None):
            raise ValueError(f"CSV line {line}: successful trials require a range; other trials leave it blank")
        reference = number(row["reference_m"], "reference_m", line) if row["reference_m"] else None
        pose = Pose(
            pose_value(row, "depth_m", 0, -30, 30, line),
            pose_value(row, "height_m", 1, 0, 10, line),
            pose_value(row, "heading_deg", 0, 0, 360, line) % 360,
            pose_value(row, "pitch_deg", 0, -90, 90, line),
            (row.get("surface") or "").strip(),
        )
        station = pose_value(row, "station_m", 0, -30, 30, line)
        trials.append(Trial(source, scene, station, reference, status, distance, pose))
    if not trials:
        raise ValueError("Record at least one scan before processing")
    return trials


def summarize(trials: list[Trial]) -> Report:
    source = trials[0].source
    groups: dict[tuple[str, float, Pose], list[Trial]] = defaultdict(list)
    for trial in trials:
        if trial.source != source:
            raise ValueError("Process measured and simulated inputs as separate files")
        groups[(trial.scene, trial.station_m, trial.pose)].append(trial)

    points: list[Point] = []
    for (scene, station, pose), group in sorted(groups.items()):
        reference_values = {trial.reference_m for trial in group if trial.reference_m is not None}
        if len(reference_values) > 1:
            raise ValueError(f"{scene} station {station:g} m has conflicting reference distances")
        reference = next(iter(reference_values), None)
        accepted = [trial.range_m for trial in group if trial.range_m is not None]
        spread = max(accepted) - min(accepted) if len(accepted) >= 2 else None
        enough_trials = len(accepted) >= 3 and len(accepted) > len(group) / 2
        estimate = statistics.median(accepted) if enough_trials and spread is not None and spread <= 0.35 else None
        error = abs(estimate - reference) if estimate is not None and reference is not None else None
        points.append({
            "scene": scene, "station_m": station, "reference_m": reference,
            "range_m": estimate, "spread_m": spread, "error_m": error,
            "accepted": len(accepted), "total": len(group),
            "depth_m": pose.depth_m, "height_m": pose.height_m, "heading_deg": pose.heading_deg,
            "pitch_deg": pose.pitch_deg, "surface": pose.surface,
        })
    return {"source": source, "points": points}


def quality_by_scene(report: Report) -> list[SceneQuality]:
    scenes: dict[str, list[Point]] = defaultdict(list)
    for point in report["points"]:
        scenes[point["scene"]].append(point)
    rows: list[SceneQuality] = []
    for scene, points in scenes.items():
        mapped = sum(point["range_m"] is not None for point in points)
        errors = [point["error_m"] for point in points if point["error_m"] is not None]
        trials = sum(point["total"] for point in points)
        usable = sum(point["accepted"] for point in points)
        rows.append({
            "scene": scene, "poses": len(points), "mapped_poses": mapped,
            "coverage_pct": 100 * mapped / len(points), "trials": trials, "usable_trials": usable,
            "usable_trial_pct": 100 * usable / trials, "reference_poses": len(errors),
            "mean_absolute_error_m": statistics.mean(errors) if errors else None,
            "max_absolute_error_m": max(errors) if errors else None,
        })
    return rows


def quality_chart(source: Source, rows: list[SceneQuality]) -> str:
    figures: list[str] = []
    for row in rows:
        error = row["mean_absolute_error_m"]
        accuracy = f"{error * 100:.1f} cm mean absolute error" if error is not None else "Awaiting tape references"
        figures.append(
            f'<div class="scene"><strong>{escape(row["scene"])}</strong>'
            f'<div class="track"><div class="bar" style="width:{row["coverage_pct"]:.2f}%"></div></div>'
            f'<small>{row["mapped_poses"]}/{row["poses"]} scan poses mapped &middot; {accuracy}</small></div>'
        )
    return (
        '<style>.echo{font:16px system-ui,sans-serif;background:#11211d;color:#eff7ed;padding:24px;'
        'border-radius:12px;max-width:850px}.echo h2{margin:0 0 6px}.echo small,.echo p{color:#c0d4c8}'
        '.echo .scene{margin-top:20px}.echo .track{height:10px;background:#344940;margin:6px 0;border-radius:5px}'
        '.echo .bar{height:100%;background:#b4f1ab;border-radius:5px}</style>'
        f'<section class="echo"><h2>Acoustic scan coverage</h2><p>{source.title()} data</p>'
        + "".join(figures) + "</section>"
    )


def reference_comparison(report: Report) -> list[tuple[str, str, float, float | None, float | None, int, int]]:
    """Include rejected poses so missing estimates remain visible beside measured error."""
    return [
        (point["scene"], point["surface"], point["reference_m"], point["range_m"],
         point["error_m"] * 100 if point["error_m"] is not None else None,
         point["accepted"], point["total"])
        for point in report["points"] if point["reference_m"] is not None
    ]


def load_trials(path: Path) -> list[Trial]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        return read_trials(file)


def write_map(report: Report, output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, allow_nan=False)
        file.write("\n")


def process(input_path: Path, output_path: Path) -> Report:
    report = summarize(load_trials(input_path))
    write_map(report, output_path)
    return report


# COMMAND ----------

if "dbutils" in globals():
    dbutils.widgets.text("input_csv", "")
    dbutils.widgets.text("output_json", "")

# COMMAND ----------

if "dbutils" in globals():
    input_csv = dbutils.widgets.get("input_csv").strip()
    output_json = dbutils.widgets.get("output_json").strip()
    if not input_csv.startswith("/Volumes/") or not output_json.startswith("/Volumes/"):
        raise ValueError("Set both widgets to full Unity Catalog volume paths beginning with /Volumes/")
    trials = load_trials(Path(input_csv))
    report = summarize(trials)
    write_map(report, Path(output_json))
    scene_quality = quality_by_scene(report)
    statuses = Counter((trial.scene, trial.status) for trial in trials)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Scan coverage and ranging error
# MAGIC Coverage is the fraction of scan poses that produced a range. Error is calculated only for mapped poses with a reference distance.

# COMMAND ----------

if "dbutils" in globals():
    displayHTML(quality_chart(report["source"], scene_quality))
    display(spark.createDataFrame(
        scene_quality,
        "scene string, poses long, mapped_poses long, coverage_pct double, "
        "trials long, usable_trials long, usable_trial_pct double, reference_poses long, "
        "mean_absolute_error_m double, max_absolute_error_m double",
    ))
    display(spark.createDataFrame(
        reference_comparison(report),
        "scene string, surface string, tape_m double, estimated_m double, "
        "absolute_error_cm double, usable_trials long, total_trials long",
    ))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Trial outcomes and map export
# MAGIC The rejection breakdown helps distinguish competing reflections, clipping, and missing pulses.

# COMMAND ----------

if "dbutils" in globals():
    display(spark.createDataFrame(
        [(scene, status, count) for (scene, status), count in sorted(statuses.items())],
        "scene string, status string, trials long",
    ))
    display(spark.createDataFrame(
        report["points"],
        "scene string, station_m double, reference_m double, range_m double, "
        "spread_m double, error_m double, accepted long, total long, "
        "depth_m double, height_m double, heading_deg double, pitch_deg double, surface string",
    ))
    print(f"{report['source'].title()} scans. Wrote {len(report['points'])} scan poses to {output_json}.")
elif __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()
    report = process(args.input_csv, args.output_json)
    print(f"{report['source'].title()} scans. Wrote {len(report['points'])} stations to {args.output_json}.")
