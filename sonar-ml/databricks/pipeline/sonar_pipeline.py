"""EchoSense sonar lakehouse: Lakeflow Declarative Pipeline (bronze -> silver -> gold). ADR-0014.

Sources (bronze):
  * landing_frames table  - written by the `generate` job task (parallel simulation)
  * landing/frames/*.npz  - SonarFrame files from recordings or a live sensor (Auto Loader)
  * landing/acoustic/*.csv - scan CSVs from the acoustic/ laptop scanner (Auto Loader)

All per-frame logic lives in `sonar_perception.lakehouse` (unit-tested locally);
this file only wires tables together and declares data-quality expectations.
"""

import dlt
from pyspark.sql import functions as F

from sonar_perception import lakehouse as L

CATALOG = spark.conf.get("sonar.catalog")  # noqa: F821 (spark is provided by the pipeline runtime)
SCHEMA = spark.conf.get("sonar.schema")  # noqa: F821
LANDING = spark.conf.get("sonar.landing_path")  # noqa: F821

ACOUSTIC_CSV_SCHEMA = (
    "source STRING, scene STRING, station_m DOUBLE, depth_m DOUBLE, height_m DOUBLE, heading_deg DOUBLE, "
    "pitch_deg DOUBLE, surface STRING, reference_m DOUBLE, trial INT, status STRING, range_m DOUBLE, "
    "echo_ratio DOUBLE"
)


# ---------------------------------------------------------------- bronze

dlt.create_streaming_table(
    "bronze_frames",
    comment="Every SonarFrame that entered the lakehouse, one row per frame (points, labels, grid, meta). "
    "Format spec: sonar-ml/docs/interfaces/sonar-frame.md. The intensity volume is not stored (ADR-0014).",
)


@dlt.append_flow(target="bronze_frames", name="frames_from_simulator")
def frames_from_simulator():
    return spark.readStream.table(f"{CATALOG}.{SCHEMA}.landing_frames")  # noqa: F821


@dlt.append_flow(target="bronze_frames", name="frames_from_files")
def frames_from_files():
    raw = (
        spark.readStream.format("cloudFiles")  # noqa: F821
        .option("cloudFiles.format", "binaryFile")
        .option("pathGlobFilter", "*.npz")
        .load(f"{LANDING}/frames")
    )
    return raw.select("path", "content").mapInPandas(L.npz_partitions(), schema=L.FRAME_SCHEMA)


@dlt.table(comment="Raw rows from acoustic/ scan CSVs (laptop speaker+mic chirp scanner), one row per trial.")
def bronze_acoustic_trials():
    return (
        spark.readStream.format("cloudFiles")  # noqa: F821
        .option("cloudFiles.format", "csv")
        .option("header", "true")
        # Explicit schema (columns of acoustic/sample-scans.csv): inference fails on an empty folder.
        .schema(ACOUSTIC_CSV_SCHEMA)
        .load(f"{LANDING}/acoustic")
        .withColumn("source_file", F.col("_metadata.file_path"))
        .withColumn("ingested_at", F.current_timestamp())
    )


# ---------------------------------------------------------------- silver

@dlt.table(comment="Frames that pass format and consistency checks.")
@dlt.expect_or_drop("supported_format_version", "format_version LIKE '0.%'")
@dlt.expect_or_drop("has_spherical_grid", "size(range_edges) > 1 AND size(az_edges) > 1 AND size(el_edges) > 1")
@dlt.expect_or_drop("point_count_matches", "n_points = size(points)")
@dlt.expect_or_drop("labels_align_with_points", "point_labels IS NULL OR size(point_labels) = n_points")
@dlt.expect("frame_has_points", "n_points > 0")
@dlt.expect("known_conditions", "conditions IS NULL OR conditions IN ('clear', 'fog', 'warm', 'heavy', 'extreme')")
def silver_frames():
    return spark.readStream.table("bronze_frames")  # noqa: F821


@dlt.table(comment="Object candidates: DBSCAN clusters (spherical coords) with 26 shape/intensity features "
           "and, for labeled frames, the majority ground-truth class. One row per cluster.")
@dlt.expect_or_drop("min_cluster_size", "n_points >= 8")
@dlt.expect_or_drop("finite_features", "NOT exists(features, x -> isnan(x) OR x IS NULL)")
@dlt.expect("within_sensor_range", "range_m BETWEEN 0.2 AND 6.5")
@dlt.expect("label_purity_ok", "purity IS NULL OR purity >= 0.5")
def silver_clusters():
    return spark.readStream.table("silver_frames").mapInPandas(  # noqa: F821
        L.cluster_partitions(), schema=L.CLUSTER_SCHEMA
    )


@dlt.table(comment="Ground-truth objects in simulated frames and how many points each produced.")
def silver_objects():
    sim = spark.readStream.table("silver_frames").where("source = 'synthetic'")  # noqa: F821
    return sim.mapInPandas(L.object_partitions(), schema=L.OBJECT_SCHEMA)


@dlt.table(comment="Acoustic trials with range error vs tape reference.")
@dlt.expect_or_drop("known_status", "status IN ('ok', 'no_direct', 'no_echo', 'ambiguous', 'clipped')")
@dlt.expect("ok_trials_have_range", "status != 'ok' OR range_m IS NOT NULL")
@dlt.expect("plausible_range", "range_m IS NULL OR range_m BETWEEN 0.3 AND 6.0")
def silver_acoustic_trials():
    return (
        spark.readStream.table("bronze_acoustic_trials")  # noqa: F821
        .withColumn("range_error_m", F.col("range_m") - F.col("reference_m"))
    )


# ---------------------------------------------------------------- gold

@dlt.table(comment="Cluster dataset balance per run, conditions, and class (what the classifier trains on).")
def gold_cluster_balance():
    return (
        spark.read.table("silver_clusters")  # noqa: F821
        .groupBy("run_id", "conditions", "label_name")
        .agg(F.count("*").alias("clusters"), F.avg("n_points").alias("avg_points"),
             F.avg("purity").alias("avg_purity"), F.avg("range_m").alias("avg_range_m"))
    )


@dlt.table(comment="How often each kind of object is visible at all (>= 8 points) by pose and conditions. "
           "Invisible objects can't be fixed by the classifier (ADR-0013).")
def gold_object_visibility():
    return (
        spark.read.table("silver_objects")  # noqa: F821
        .where("name != 'floor'")
        .withColumn("range_band", F.when(F.col("range_m") < 2.25, "<2.25 m")
                    .when(F.col("range_m") < 4.0, "2.25-4 m").otherwise(">4 m"))
        .groupBy("run_id", "class_name", "variant", "conditions", "range_band")
        .agg(F.count("*").alias("objects"),
             F.avg((F.col("n_points") >= 8).cast("double")).alias("visible_rate"),
             F.avg("n_points").alias("avg_points"))
    )


@dlt.table(comment="Acoustic scan quality per scene: acceptance rate and range error vs tape reference.")
def gold_acoustic_quality():
    return (
        spark.read.table("silver_acoustic_trials")  # noqa: F821
        .groupBy("source", "scene")
        .agg(F.count("*").alias("trials"),
             F.avg((F.col("status") == "ok").cast("double")).alias("ok_rate"),
             F.expr("percentile_approx(abs(range_error_m), 0.5)").alias("median_abs_error_m"),
             F.max(F.abs("range_error_m")).alias("max_abs_error_m"))
    )
