"""Job task 4: score frames with the @champion model -> gold_detections, gold_object_outcomes + summary views.

Outcomes follow every ground-truth object end to end (invisible / merged /
fragmented / wrong / correct), the same measure as the `diagnose` CLI. Quote
those numbers, not cluster accuracy (AGENTS.md rule 7).
"""

import argparse

from pyspark.sql import SparkSession

from sonar_perception import lakehouse as L
from sonar_perception.lakehouse_model import load_feature_forest


def _replace_run(spark, df, table: str, run_id: str) -> None:
    if spark.catalog.tableExists(table):
        spark.sql(f"DELETE FROM {table} WHERE run_id = '{run_id}'")
    df.write.mode("append").option("mergeSchema", "true").saveAsTable(table)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--model-name", required=True)
    ap.add_argument("--alias", default="champion")
    a = ap.parse_args()

    import mlflow

    spark = SparkSession.builder.getOrCreate()
    try:
        spark.conf.set("spark.sql.execution.arrow.maxRecordsPerBatch", "32")
    except Exception:  # some serverless confs are locked; the default still works, just uses more memory
        pass
    fq = f"{a.catalog}.{a.schema}"

    mlflow.set_registry_uri("databricks-uc")
    local = mlflow.artifacts.download_artifacts(artifact_uri=f"models:/{a.model_name}@{a.alias}")
    model = load_feature_forest(local)
    print(f"scoring run {a.run_id} with {a.model_name}@{a.alias} ({model.full_name})")

    frames = spark.table(f"{fq}.silver_frames").where(f"run_id = '{a.run_id}'")
    split = spark.table(f"{fq}.gold_split").where(f"run_id = '{a.run_id}'")

    dets = frames.mapInPandas(L.detection_partitions(model), schema=L.DETECTION_SCHEMA)
    outs = frames.mapInPandas(L.outcome_partitions(model), schema=L.OUTCOME_SCHEMA)
    dets = dets.join(split, ["run_id", "scene_id"], "left")
    outs = outs.join(split, ["run_id", "scene_id"], "left")
    _replace_run(spark, dets, f"{fq}.gold_detections", a.run_id)
    _replace_run(spark, outs, f"{fq}.gold_object_outcomes", a.run_id)

    spark.sql(f"""
        CREATE OR REPLACE VIEW {fq}.gold_end_to_end AS
        SELECT run_id, model, split, class_name, variant, conditions,
               COUNT(*) AS objects,
               AVG(CASE WHEN outcome = 'correct' THEN 1.0 ELSE 0.0 END) AS correct_rate,
               AVG(CASE WHEN outcome = 'invisible' THEN 1.0 ELSE 0.0 END) AS invisible_rate,
               AVG(CASE WHEN outcome = 'merged' THEN 1.0 ELSE 0.0 END) AS merged_rate,
               AVG(CASE WHEN outcome LIKE 'wrong:%' THEN 1.0 ELSE 0.0 END) AS misclassified_rate
        FROM {fq}.gold_object_outcomes
        GROUP BY ALL
    """)
    spark.sql(f"""
        CREATE OR REPLACE VIEW {fq}.gold_person_alerts AS
        SELECT run_id, model, split,
               COUNT(DISTINCT frame_id) AS frames,
               COUNT(*) AS person_alerts,
               AVG(CASE WHEN gt_class = 'person' THEN 1.0 ELSE 0.0 END) AS person_precision,
               SUM(CASE WHEN gt_class = 'noise' THEN 1 ELSE 0 END) AS alerts_on_noise
        FROM {fq}.gold_detections
        WHERE class_name = 'person'
        GROUP BY ALL
    """)

    summary = spark.sql(f"""
        SELECT variant, ROUND(AVG(CASE WHEN outcome = 'correct' THEN 1.0 ELSE 0.0 END), 3) AS correct_rate,
               COUNT(*) AS people
        FROM {fq}.gold_object_outcomes
        WHERE run_id = '{a.run_id}' AND split = 'test' AND class_name = 'person'
        GROUP BY variant ORDER BY variant
    """)
    summary.show()


if __name__ == "__main__":
    main()
