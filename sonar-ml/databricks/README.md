# databricks/ — sonar lakehouse on Databricks

The perception data pipeline as a **Databricks Asset Bundle** (`../databricks.yml`):
parallel simulation → bronze/silver/gold tables with data-quality checks →
MLflow-tracked training → Unity Catalog model → scored detection tables.
Why it's shaped this way: [ADR-0014](../docs/decisions/0014-databricks-lakehouse.md).

> Status 2026-11-14: **deployed and run end to end** on the lead's Free Edition
> workspace (dev target). A 200-scene run (`seed 2`) took ~8 min: generate →
> pipeline → train (registered v1 `@champion`) → score. Not yet exercised: the
> `.npz` and acoustic Auto Loader sources with real files, and runs at 2,000+ scenes.

## What runs

One job, `echosense-sonar-lakehouse`, four tasks. Every row is tagged
`run_id = run<job run id>`.

| Task | Code | Does | Writes |
|---|---|---|---|
| `generate` | `jobs/generate.py` | Simulates `n_scenes` in parallel (`spark.range` → `mapInPandas`), same RNG as the local CLI | `landing_frames` |
| `refresh_pipeline` | `pipeline/sonar_pipeline.py` | Lakeflow Declarative Pipeline: bronze → silver → gold, with expectations | see below |
| `train` | `jobs/train.py` | Random forest on `silver_clusters`, split by scene; MLflow params/metrics/artifacts; registers a pyfunc model with the person bias built in; alias `@champion` | `gold_split`, MLflow run, UC model version |
| `score` | `jobs/score.py` | Scores frames with `@champion`; end-to-end outcome of every ground-truth object | `gold_detections`, `gold_object_outcomes`, views `gold_end_to_end`, `gold_person_alerts` |

Job parameters (defaults = recommended settings): `n_scenes 2000`, `seed 0`,
`env_mode random`, `pings 4`, `sweep 1`, `min_views 1`, `tilt 0`,
`person_bias 2`, `partitions 64`. **Change `seed` between runs** or you get the
same scenes again.

## Tables (`<catalog>.<schema>`, default `workspace.echosense_sonar`, dev mode prefixes the schema)

| Layer | Table | Grain | Source |
|---|---|---|---|
| landing | `landing_frames` | frame | `generate` task |
| landing | volume `landing/frames/*.npz` | file | recorded/live `SonarFrame` files (`SonarFrame.save`) |
| landing | volume `landing/acoustic/*.csv` | file | CSVs from the `acoustic/` scanner ("Download scan CSV") |
| bronze | `bronze_frames` | frame | both frame sources (two append flows) |
| bronze | `bronze_acoustic_trials` | trial | Auto Loader on `landing/acoustic` |
| silver | `silver_frames` | frame | expectations: format 0.x, grid present, point/label counts consistent |
| silver | `silver_clusters` | cluster | DBSCAN + 26 features; drop < 8 points or non-finite features |
| silver | `silver_objects` | GT object | simulated frames only |
| silver | `silver_acoustic_trials` | trial | + `range_error_m` vs tape reference |
| gold | `gold_cluster_balance` | run × conditions × class | what the classifier trains on |
| gold | `gold_object_visibility` | run × class × pose × conditions × range band | how often objects are visible at all |
| gold | `gold_acoustic_quality` | scene | acceptance rate, median range error |
| gold | `gold_split` | run × scene | train/test assignment |
| gold | `gold_detections` | detection | model output (noise clusters omitted, like `detect`) |
| gold | `gold_object_outcomes` | GT object | correct / invisible / merged / fragmented / wrong:X |
| gold | `gold_end_to_end` (view) | run × split × class × pose × conditions | the numbers to quote (AGENTS.md rule 7) |
| gold | `gold_person_alerts` (view) | run × split | person precision, alerts on noise |

The intensity **volume is not stored** in tables (≈0.8 MB/frame, unused after
point extraction). Keep `.npz` files if you need it.

## Deploy (from `sonar-ml/`)

Needs the Databricks CLI (v0.250+ recommended) and a workspace (Free Edition works:
serverless only, no GPUs).

```bash
databricks auth login --host https://<your-workspace>.cloud.databricks.com
databricks bundle validate
databricks bundle deploy
databricks bundle run sonar_lakehouse                      # full job with defaults
databricks bundle run sonar_lakehouse --params n_scenes=200,seed=1   # quick run
```

Real acoustic scans into the lakehouse (then re-run the job or just the pipeline):

```bash
databricks fs cp ../acoustic/sample-scans.csv dbfs:/Volumes/workspace/<schema>/landing/acoustic/
```

Recorded `SonarFrame` files the same way into `landing/frames/`.

## Known gotchas (from the first deploy)

- Resource keys must be unique across all resource types in the bundle
  (a job and a pipeline can't both be `sonar_lakehouse`).
- The pipeline installs the **uploaded wheel** by exact file name
  (`.../artifacts/.internal/sonar_perception-0.1.0-py3-none-any.whl`). Bump it in
  `resources/pipeline.yml` if the package version changes. `--editable` of the
  bundle files did not work.
- A failing pipeline retries several times before the job gives up (~14 min).
  To debug, run the pipeline alone: `databricks bundle run sonar_pipeline`.
- Dev mode prefixes the schema and model: `workspace.dev_<user>_echosense_sonar`,
  model `dev_<user>_sonar_cluster_classifier`.

## Local testing

```bash
.venv/bin/pip install -e "perception[dev,spark]"          # spark extra needs Java 17+
cd perception && ../.venv/bin/python -m pytest tests/test_lakehouse.py tests/test_lakehouse_spark.py
```

The Spark test runs the exact `mapInPandas` calls of the jobs and evaluates
every expectation SQL string from `pipeline/sonar_pipeline.py`.

## Next (not built yet)

- **Model Serving endpoint** for `@champion` (input: 26 feature columns; the
  pyfunc already applies the bias). Not in the bundle because the endpoint
  needs a model version to exist first.
- **AI/BI dashboard + Genie space** over the gold tables.
- **EchoSense viewer as a Databricks App**, reading `gold_detections`.
- Deep models on `silver_clusters` (needs cluster point sets stored; GPUs
  not available on Free Edition).
