"""Job task 3: train the cluster classifier on `silver_clusters`, log to MLflow, register in Unity Catalog.

Split is by scene (ADR-0005). The registered model is an MLflow pyfunc that
takes the 26 feature columns and applies the person bias itself (ADR-0012),
so batch scoring and a Model Serving endpoint give identical answers.
"""

import argparse
import json
import os
import tempfile

import numpy as np
import pandas as pd
from pyspark.sql import SparkSession

import sonar_perception
from sonar_perception import lakehouse as L
from sonar_perception.features import FEATURE_NAMES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--person-bias", type=float, default=2.0)
    ap.add_argument("--test-frac", type=float, default=0.2)
    ap.add_argument("--n-estimators", type=int, default=300)
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--model-name", required=True, help="catalog.schema.model")
    ap.add_argument("--alias", default="champion")
    a = ap.parse_args()

    import joblib
    import mlflow
    import sklearn
    from mlflow.models import infer_signature

    from sonar_perception.lakehouse_model import SonarClusterClassifier, predictions_frame

    spark = SparkSession.builder.getOrCreate()
    fq = f"{a.catalog}.{a.schema}"
    rows = (
        spark.table(f"{fq}.silver_clusters")
        .where(f"run_id = '{a.run_id}' AND label IS NOT NULL")
        .select("scene_id", "conditions", "features", "label")
        .toPandas()
    )
    if rows.empty:
        raise RuntimeError(f"no labeled clusters for run {a.run_id}; did the pipeline refresh?")
    X = np.stack(rows["features"].to_numpy()).astype(float)
    bias = {"person": a.person_bias} if a.person_bias != 1 else {}
    model, metrics, test = L.train_forest(
        X, rows["label"].to_numpy(int), rows["scene_id"].to_numpy(), rows["conditions"].to_numpy(),
        seed=a.seed, test_frac=a.test_frac, n_estimators=a.n_estimators, bias=bias,
    )
    confusion = metrics.pop("_confusion")

    # Record the scene split so `score` reports metrics on held-out scenes only.
    split = (
        pd.DataFrame({"scene_id": rows["scene_id"], "split": np.where(test, "test", "train")})
        .drop_duplicates()
        .assign(run_id=a.run_id)
    )
    spark.sql(f"CREATE TABLE IF NOT EXISTS {fq}.gold_split (run_id STRING, scene_id INT, split STRING)")
    spark.sql(f"DELETE FROM {fq}.gold_split WHERE run_id = '{a.run_id}'")
    spark.createDataFrame(split[["run_id", "scene_id", "split"]]).write.mode("append").saveAsTable(f"{fq}.gold_split")

    sensing = spark.table(f"{fq}.landing_frames").where(f"run_id = '{a.run_id}'").select("sensing_json").first()

    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment(a.experiment)
    with mlflow.start_run(run_name=a.run_id), tempfile.TemporaryDirectory() as tmp:
        mlflow.log_params({
            "data_run_id": a.run_id, "seed": a.seed, "test_frac": a.test_frac,
            "n_estimators": a.n_estimators, "bias": json.dumps(bias),
            "sensing": sensing["sensing_json"] if sensing else None,
            "n_scenes": int(rows["scene_id"].nunique()), "features": len(FEATURE_NAMES),
        })
        mlflow.log_metrics(metrics)
        mlflow.log_dict(confusion, "confusion_matrix.json")
        mlflow.log_dict(
            dict(sorted(zip(FEATURE_NAMES, model.forest.feature_importances_.round(4).tolist()), key=lambda kv: -kv[1])),
            "feature_importance.json",
        )

        forest_path, bias_path = os.path.join(tmp, "forest.joblib"), os.path.join(tmp, "bias.json")
        joblib.dump(model.forest, forest_path)
        with open(bias_path, "w") as f:
            json.dump(bias, f)
        example = pd.DataFrame(X[:5], columns=FEATURE_NAMES)
        info = mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=SonarClusterClassifier(),
            artifacts={"forest": forest_path, "bias": bias_path},
            code_paths=[os.path.dirname(sonar_perception.__file__)],
            signature=infer_signature(example, predictions_frame(model, example)),
            input_example=example,
            pip_requirements=[f"scikit-learn=={sklearn.__version__}", f"numpy=={np.__version__}", "scipy",
                              "joblib", "pandas"],
        )
        version = mlflow.register_model(info.model_uri, a.model_name)
        mlflow.MlflowClient().set_registered_model_alias(a.model_name, a.alias, version.version)

    print(f"accuracy {metrics['accuracy']:.3f}  person recall {metrics.get('recall_person', float('nan')):.3f}  "
          f"precision {metrics.get('precision_person', float('nan')):.3f}  (cluster level, test scenes)")
    print(f"registered {a.model_name} v{version.version} as @{a.alias}")


if __name__ == "__main__":
    main()
