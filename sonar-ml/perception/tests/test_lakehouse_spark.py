"""Local Spark smoke test for the Databricks code path (ADR-0014).

Runs the same mapInPandas calls as databricks/jobs/*.py and the pipeline,
and checks every expectation SQL expression in the pipeline parses and runs.
Skipped unless pyspark and Java are installed (`pip install -e "perception[spark]"`).
"""

import pathlib
import re
import shutil

import pytest

pytest.importorskip("pyspark")
pytest.importorskip("pandas")
if not shutil.which("java"):
    pytest.skip("Java not installed", allow_module_level=True)

from sonar_perception import lakehouse as L  # noqa: E402

PIPELINE = pathlib.Path(__file__).resolve().parents[2] / "databricks" / "pipeline" / "sonar_pipeline.py"


@pytest.fixture(scope="module")
def spark():
    import os
    import sys

    from pyspark.sql import SparkSession

    # Python workers must use this interpreter, not whatever `python3` is on PATH
    # (on the lead's Mac that's Anaconda with old numpy/pyarrow; see log 2026-11-14 session 6).
    os.environ["PYSPARK_PYTHON"] = sys.executable
    os.environ["PYSPARK_DRIVER_PYTHON"] = sys.executable

    s = (SparkSession.builder.master("local[2]").appName("sonar-lakehouse-test")
         .config("spark.sql.execution.arrow.maxRecordsPerBatch", "8")
         .config("spark.ui.enabled", "false").getOrCreate())
    yield s
    s.stop()


@pytest.fixture(scope="module")
def frames(spark):
    scenes = spark.range(6).withColumnRenamed("id", "scene_index").repartition(3)
    return scenes.mapInPandas(L.generate_partitions("spark1", seed=1), schema=L.FRAME_SCHEMA).cache()


def _expectations(table: str) -> list[str]:
    """SQL strings of the @dlt.expect* decorators directly above `def <table>()`."""
    text = PIPELINE.read_text()
    block = text[: text.index(f"def {table}():")].rsplit("@dlt.table", 1)[1]
    return re.findall(r'@dlt\.expect(?:_or_drop)?\("[^"]+", "([^"]+)"\)', block)


def test_generate_and_silver_frames(frames):
    rows = frames.collect()
    assert len(rows) == 6 and all(r.n_points == len(r.points) for r in rows)
    exprs = _expectations("silver_frames")
    assert len(exprs) >= 5
    for e in exprs:
        assert frames.where(e).count() == 6, e


def test_clusters_objects_and_expectations(frames):
    clusters = frames.mapInPandas(L.cluster_partitions(), schema=L.CLUSTER_SCHEMA).cache()
    n = clusters.count()
    assert n > 0
    for e in _expectations("silver_clusters"):
        clusters.where(e).count()  # parses and runs
    big = clusters.where("n_points >= 8").count()
    assert big == n  # extract_clusters already drops clusters under 8 points
    objects = frames.mapInPandas(L.object_partitions(), schema=L.OBJECT_SCHEMA)
    assert objects.count() > 0


def test_train_score_roundtrip(frames):
    import numpy as np

    clusters = frames.mapInPandas(L.cluster_partitions(), schema=L.CLUSTER_SCHEMA).where("label IS NOT NULL")
    pdf = clusters.select("scene_id", "conditions", "features", "label").toPandas()
    model, _, _ = L.train_forest(np.stack(pdf["features"].to_numpy()), pdf["label"].to_numpy(int),
                                 pdf["scene_id"].to_numpy(), n_estimators=20, bias={"person": 2})
    dets = frames.mapInPandas(L.detection_partitions(model), schema=L.DETECTION_SCHEMA)
    outs = frames.mapInPandas(L.outcome_partitions(model), schema=L.OUTCOME_SCHEMA)
    assert dets.count() > 0
    assert outs.where("outcome IS NULL").count() == 0
