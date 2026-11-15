# 2026-11-15 ? isolated backend / synthetic model sprint

Branch baseline PR #8 a63ebf3; read instructions, fetched refs, preserved every
existing worktree and the completed 26-file combined viewer. No pushes or merges.
Perception matches databricks-pipeline; its newer mapper changes were not merged.

RF and DBSCAN imports now worked in the previously isolated environment; older
Application Control blocks did not recur. No reinstall or OS policy change.
First pytest attempt had 31 passes and six fixture setup errors because my new
basetemp parent was absent; corrected baseline run passed 37 with one Spark skip.
An early report-edit command used the wrong cwd and changed nothing; corrected
before evaluation. Original data generation completed before augmentation edits.

Generated 400 nominal training scenes, 120 unchanged standard holdout scenes,
120 acquisition-shift holdout scenes, 400 mixed candidate scenes. Inputs locked
before fitting; trained baseline and one candidate configuration across seeds
0/1/2, common scene split. Hypothesis: acquisition diversity improves shift
robustness without unacceptable nominal loss. Challenge F1 improved .0996 but
standard F1 fell .0556; person nominal recall fell .0308. Hypothesis failed its
non-regression guard: RETAIN BASELINE. No further candidate search was run.

Added no-op/bounds/label-alignment/nonmutation and artifact-preservation tests.
Final perception 47 pass +1 Spark skip; mapper 20 pass +1 Windows pty skip;
bridge 130 pass; Node 41 pass; synthetic serial contract 8 pass. Tests produced
sklearn parallel-configuration warnings (not assertion failures).

Fresh mapper/WebSocket/browser regression passed functional rendering, sonar
markers, Room analysis and PNG, while confirming existing provenance/fallback
failures. No active UI, firmware or mapper source edits were made. Backend-only
source metadata would not fix the adapter's hard-coded live values. Exact owner
recommendations and limitations recorded in report; no real sensor claims.

Artifacts: sonar-ml/data/model-sprint-20261115 (ignored); compact evidence is
versioned in docs/reports/model-sprint-20261115. Full models/NPZ/logs preserved.
