# ADR-0014: Run the perception data pipeline on Databricks as an Asset Bundle

- **Status:** accepted (code written and tested locally; not yet deployed)
- **Date:** 2026-11-14
- **Area:** perception + project (MadHacks Databricks track)

## Context
The team is targeting the Databricks track. Until now the pipeline was a local
CLI writing `.npz` files (`generate` → `baseline` → `detect` / `diagnose`).
Teammates also produce data elsewhere: `acoustic/` writes scan CSVs, and a
future sensor will write `SonarFrame` files. We want one place where all of it
lands, is quality-checked, trains the model, and feeds the demo.

## Decision
1. **Asset Bundle in `sonar-ml/`** (`databricks.yml` + `databricks/`): schema,
   landing volume, MLflow experiment, UC registered model, a Lakeflow
   Declarative Pipeline, and one 4-task job, all as code in the repo.
2. **Medallion tables** (bronze → silver → gold) built by the pipeline, with
   data-quality **expectations** on frames, clusters and acoustic trials.
   Two frame sources feed `bronze_frames`: the simulator's `landing_frames`
   table and Auto Loader on `.npz` files in the landing volume (the path real
   recordings will take). Acoustic CSVs get their own bronze/silver/gold.
3. **Parallel simulation** with `spark.range(n).mapInPandas(...)`. It uses the
   same RNG stream as the CLI, so scene *i* of seed *s* is identical locally
   and on Databricks (tested).
4. **All per-frame logic stays in the package** (`sonar_perception.lakehouse`):
   plain Python/pandas functions with Spark DDL schemas. Spark and Databricks
   code only wires them together. Tested locally with pandas and with a
   real local Spark session.
5. **MLflow**: one run per training, params (sensing, bias, seed), cluster-level
   metrics, confusion matrix, feature importance. The model is registered as a
   **pyfunc that applies the person bias itself** (ADR-0012), so serving and
   batch scoring agree with `detect --bias person=2`. Alias `@champion` is
   what `score` uses.
6. **End-to-end metrics in gold** (`gold_object_outcomes`, `gold_end_to_end`),
   not just cluster accuracy (AGENTS.md rule 7). Test-split rows only for
   reporting.
7. **Don't store the intensity volume in tables.** It's ~0.8 MB per frame and
   nothing after point extraction reads it. `row_to_frame` rebuilds a frame
   with a zero volume and `meta.volume_stored = false`.
8. **Job tasks are Python scripts with a wheel** (built from `perception/`),
   not notebooks, because Spark UDFs need `sonar_perception` on the executors
   and serverless job environments install wheels everywhere. The pipeline
   installs the same uploaded wheel (an `--editable` install of the bundle
   files did not work on first deploy).

## Alternatives considered
- **Notebooks only:** easier to show, but installing the package for UDFs on
  serverless notebooks is awkward, and nothing would be versioned as deployable
  code. Can add display notebooks later that read the gold tables.
- **Store `.npz` files only, no tables:** loses expectations, SQL and dashboards,
  and is weak for the track.
- **Exploded per-point table:** ~9k points per frame × thousands of frames is
  tens of millions of rows nobody queries. Points stay as an array per frame.

## Consequences
- The pipeline runs on any Databricks workspace including Free Edition
  (serverless, CPU). Deep models would be slow there.
- `landing_frames` must exist before the first pipeline update; the job's
  `generate` task creates it.
- Deployed and run end to end on 2026-11-14 (Free Edition, 200 scenes). See
  `databricks/README.md` for the gotchas found on first deploy.
