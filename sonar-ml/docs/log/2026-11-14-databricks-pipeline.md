# 2026-11-14 (session 6) — Databricks pipeline

_Goal from the lead: "create a new branch and start building on the databricks
pipeline" (the team is targeting the MadHacks Databricks track). Branch
`databricks-pipeline` in EchoSense. Decision record:
[ADR-0014](../decisions/0014-databricks-lakehouse.md)._

## Context from the conversation
- Researched Databricks Free Edition limits: serverless only, no GPUs, small
  quotas (few concurrent job tasks, limited serving endpoints). The random
  forest and the simulator are CPU-only, so this fits.
- Scenario discussion: the lead worried fire noise drowns sonar. Our view
  (unverified): fire noise is mostly below 10 kHz, the 40 kHz chirp plus matched
  filter rejects most of it, and heat/turbulence is the bigger risk. Suggested a
  campfire recording with an ultrasonic mic to check. Considered collapsed-building
  search and rescue instead, then rejected it as the main pitch: in-air
  ultrasound can't see through rubble, so buried victims are out of reach.
  **Main pitch stays: room-by-room search in smoke.**

## Built
- `sonar_perception/lakehouse.py`: frame/cluster/object/detection/outcome rows,
  Spark DDL schemas, `mapInPandas`-ready partition functions, `FeatureForest`
  (RF + bias on stored features), `train_forest` (scene split).
- `sonar_perception/lakehouse_model.py`: MLflow pyfunc wrapper (bias built in).
- `databricks.yml` + `databricks/`: catalog resources, Lakeflow pipeline with
  expectations, 4-task job (`generate`, `refresh_pipeline`, `train`, `score`).
- Tests: `test_lakehouse.py` (10, pandas) and `test_lakehouse_spark.py` (3, real
  local Spark; evaluates every pipeline expectation string). 40 tests pass.

## Trial and error
- **Local Spark failed with `'pyarrow.lib.StructType' object has no attribute
  'names'`.** I first blamed pyspark/pyarrow version skew and tried pyspark 4.0
  (fails on Java 24: `getSubject is not supported`), 4.2 and 4.1. The real
  cause: **Spark's Python workers ran Anaconda's `python3`** (old numpy and
  pyarrow), not the venv. Fix: set `PYSPARK_PYTHON` to `sys.executable` in the
  test fixture. Back on pyspark 4.3 / pyarrow 26 / pandas 3: passes.
- Floor objects carry the wall class id (ADR-0010), so per-class outcomes
  counted the floor as a wall to find. `outcome_rows` now drops `name == 'floor'`.
- Acoustic Auto Loader originally inferred the CSV schema, which fails on an
  empty folder. Switched to an explicit schema.

## First deploy (Free Edition workspace, dev target)
- Installed the Databricks CLI v1.26.0 from the official GitHub release
  (checksum verified; Homebrew is broken on this Mac). Lead signed in via OAuth.
- `bundle validate` failed: duplicate resource keys (`sonar_lakehouse` for both
  job and pipeline; `sonar` for schema and experiment). Renamed to
  `sonar_pipeline`, `sonar_experiment`.
- Run 1: `generate` worked (200 frames); the pipeline failed 5× with
  `No module named sonar_perception`, so the job took ~14 min to fail. The
  `--editable ${workspace.file_path}/perception` dependency did not install the
  package. Fix: depend on the wheel the bundle uploads
  (`${workspace.artifact_path}/.internal/sonar_perception-0.1.0-py3-none-any.whl`).
  Pipeline alone then completed.
- Run 2 (`n_scenes=200, seed=2`): **all 4 tasks succeeded in ~8 min.**
  Cluster level (test scenes): accuracy 0.834, person recall 0.933, precision
  0.609. End to end, people correct on test scenes: standing 0.63 (19),
  crouching 0.56 (9), lying 0.64 (11). Tiny sample (39 people, 200-scene
  model); don't compare with the 1,000-scene local numbers yet.

## Not done / unverified
- Auto Loader sources with real `.npz` / acoustic CSV files; 2,000-scene runs.
- Not built yet: serving endpoint, dashboard/Genie, Databricks App.
