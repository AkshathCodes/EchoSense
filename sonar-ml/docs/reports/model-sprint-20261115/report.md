# Backend synthetic-model sprint ? 2026-11-15

## Decision: RETAIN BASELINE

The candidate improves acquisition-shift robustness but significantly regresses the
unchanged standard holdout and person end-to-end recall. It is not promoted.
All measurements are synthetic; no live-demo model improvement is claimed.

## Baseline and actual consumer

Baseline code: PR #8 `a63ebf3fb022efa9ac91140aae7e88510638f33a`.
`sonar-ml/perception` is identical on current `databricks-pipeline` (`4f2bef7`);
no branch merge is needed. This branch includes the former mapper/Databricks
integration, but no model is loaded by the live viewer.

Live path: iPhone binary depth + IMU -> `lidar_mapper.Mapper` (IMU/ICP, voxel map)
-> `LiveMapper.snapshot()` (sonar_frame v0.1 with `meta.kind=lidar_map`)
-> `src/mapper-adapter.js` (axes `[-left, up, -forward]`) -> JavaScript
`classifyRoom` -> `drawRoomPlan`. Room analysis is geometric rules, not ML.
Its labels are floor/wall/ceiling/object, not the forest's six labels.

Trainable path: simulated/recorded SonarFrame v0.2 -> spherical DBSCAN
(eps .12, angular scale 2, min_samples 4, min_points 8) -> 26 existing
`FEATURE_NAMES` -> 300-tree balanced random forest -> detections v0.1.
Features cover counts, extents, PCA shape/orientation, absolute height/range,
SNR statistics, height-width profiles and density. See the unchanged features.py.
`ForestClassifier` loads raw sklearn `.joblib`; optional PointNet/BEV/voxel
models load `best.pt` through `TorchClassifier`. Neither is part of Room analysis.
No existing joblib/PT model artifacts were found in the inspected local worktrees;
the historical 2,000-scene production dataset/weights were unavailable. Therefore
this reproduces the checked-in procedure, not its published historical scores.

`codex/ultrasonic-scan` has a separate `acoustic/train_demo_model.py` experiment
and Web Serial capture. It also uses the sonar-perception forest, but is not
merged here or substituted for the mapper. No hyperparameter search was run.

## Fixed inputs and leakage controls

- `baseline-train`: seed 20261115, 400 scenes, 1725 clusters; counts in class order wall/doorway/furniture/debris/person/noise: 494/141/453/215/272/150.
- `eval-standard`: seed 424242, 120 scenes, 542 clusters; counts in class order wall/doorway/furniture/debris/person/noise: 143/27/148/70/98/56.
- `eval-challenge`: seed 424243, 120 scenes, 413 clusters; counts in class order wall/doorway/furniture/debris/person/noise: 96/39/120/49/57/52.
- `candidate-train`: seed 20261115, 400 scenes, 1610 clusters; counts in class order wall/doorway/furniture/debris/person/noise: 433/138/413/213/251/162.

Train and candidate use identical original room seeds; augmentation has its own
RNG stream `[seed, scene_id, 739391]`. A common scene split (seed 0, 20% validation)
is taken from the baseline and reused for the candidate. The baseline has
389 scenes with extracted clusters: 311 train, 78 validation. The candidate has
388 observed scenes: 310 train, the same 78 validation. Generated but unextracted
scenes remain part of the simulation manifest and end-to-end accounting. No augmented version of
a validation room is trained on. Primary evaluation uses two independently seeded,
fixed 120-scene datasets, locked before fitting; scene IDs are scoped by generator
seed. No candidate selection/tuning on test outcomes and no cluster-level split.
Exact configs and SHA-256s (including every saved evaluation frame) are in inputs.json.

The historical single-ping default is held fixed: no sweep, no person probability
bias. These results are not comparable to historical four-ping/person=2 scores.

## Candidate data changes

Opt-in `AcquisitionDiversity`; default generation is unchanged and tested against
a no-op profile. The candidate keeps 50% of scenes nominal (actual 206/400) and
changes acquisition on 194/400 scenes. Each preserves ground-truth labels:

- Sensor height 0.95?1.65 m: translate the entire scene vertically; normals and
  relative geometry remain unchanged. This challenges the fixed chest-height prior.
- Per-object reflectivity gain 0.5?1.5, independent of labels, clipped to 0.05?1:
  reduces dependence on a fixed material-strength value for each class.
- Pitch -10?20 degrees and effective max range 3.5?6 m: changes visible/occluded
  portions through the existing acoustic simulator rather than inventing points.
- Retain 65?100% of extracted points: approximates missed detections and density
  changes. Raw volume is retained; this classifier consumes points only.

Challenge scenes use height 0.8?1.8 m, gain 0.4?1.7, pitch -15?25 degrees,
range 3?5.5 m, and 45?75% point retention. One challenge frame is empty and is
kept for end-to-end analysis. Empty/no-return frames never become zero distance
or invented classified objects. Values are uncalibrated augmentation assumptions,
not measurements of HC-SR04, smoke, fog or real people.

## Controlled training and results

Both forests: 300 trees, `class_weight=balanced`, defaults otherwise, `n_jobs=1`
for bounded/reproducible CPU use. Forest seeds 0,1,2; common split seed 0. Models
are retained independently under `sonar-ml/data/model-sprint-20261115/results/`.
Production inference and existing weights were not changed. Model file sizes
and SHA-256 checksums are recorded in model-artifacts.json.

Mean across three forest seeds; accuracy/F1 are fractions:

| Holdout | Metric | Baseline | Candidate | Delta |
|---|---|---|---|---|
| standard | accuracy | 0.8370 | 0.7897 | -0.0474 |
| standard | macro_f1 | 0.8222 | 0.7666 | -0.0556 |
| challenge | accuracy | 0.6199 | 0.7111 | +0.0912 |
| challenge | macro_f1 | 0.5929 | 0.6925 | +0.0996 |

Paired whole-scene bootstrap, seed-0 accuracy delta, 1,000 resamples:
standard 95% interval [-0.07455, -0.02062]; challenge [0.06029, 0.13568].
These are synthetic scene-sampling intervals, not real-sensor guarantees.

Person end-to-end recall (seed 0, all ground-truth instances, including misses):
standard 72/130 = 55.38% -> 68/130 = 52.31%; challenge 29/119 = 24.37% ->
32/119 = 26.89%. The three-seed check applies to cluster metrics; full-object
diagnostics were run for seed 0 only. Use unrounded counts in metrics.json.

Predeclared adoption rule: standard macro-F1 drop <=.01, challenge macro-F1 gain
>=.02, and standard person end-to-end recall drop <=.02. Two guards fail.

- baseline-s0: train clusters 1323, validation 402, fit 2.058 s, train accuracy 1.0000, validation accuracy 0.7935.
- baseline-s1: train clusters 1323, validation 402, fit 1.551 s, train accuracy 1.0000, validation accuracy 0.8109.
- baseline-s2: train clusters 1323, validation 402, fit 1.571 s, train accuracy 1.0000, validation accuracy 0.8109.
- candidate-s0: train clusters 1232, validation 378, fit 1.353 s, train accuracy 1.0000, validation accuracy 0.7593.
- candidate-s1: train clusters 1232, validation 378, fit 1.440 s, train accuracy 0.9992, validation accuracy 0.7778.
- candidate-s2: train clusters 1232, validation 378, fit 1.516 s, train accuracy 1.0000, validation accuracy 0.7751.

All forests have training accuracy 1.0 while validation/held-out accuracy is
substantially lower: a clear overfitting/domain-shift risk. The candidate's
challenge gain occurs across all classes, but every standard-cohort class loses
F1. Standard doorway F1 drops .839 -> .721. Seed-0 standard disagreements include
40 baseline-correct/candidate-wrong versus 15 reverse; challenge 11 versus 52.
Both models detect zero lying-person instances in these held-outs. At >4 m,
challenge invisibility is 88.9%; a classifier cannot recover missing returns.
Candidate height diversity reduces, but does not eliminate, height-feature
reliance (`z_max` importance .132 -> .120, centroid_z .117 -> .083).

Seed-0 inference ms/cluster: standard .0958 -> .0800; challenge .1210 -> .0814.
These single local timing samples are not a performance guarantee.

### standard, forest seed 0

| Class | Baseline P / R / F1 | Candidate P / R / F1 |
|---|---|---|
| wall | 0.971 / 0.937 / 0.954 | 0.935 / 0.909 / 0.922 |
| doorway | 0.743 / 0.963 / 0.839 | 0.647 / 0.815 / 0.721 |
| furniture | 0.863 / 0.764 / 0.810 | 0.808 / 0.709 / 0.755 |
| debris | 0.667 / 0.886 / 0.761 | 0.671 / 0.786 / 0.724 |
| person | 0.849 / 0.745 / 0.793 | 0.831 / 0.704 / 0.762 |
| noise | 0.729 / 0.768 / 0.748 | 0.608 / 0.804 / 0.692 |
### challenge, forest seed 0

| Class | Baseline P / R / F1 | Candidate P / R / F1 |
|---|---|---|
| wall | 0.893 / 0.698 / 0.784 | 0.917 / 0.802 / 0.856 |
| doorway | 0.487 / 0.487 / 0.487 | 0.585 / 0.615 / 0.600 |
| furniture | 0.563 / 0.708 / 0.627 | 0.699 / 0.717 / 0.708 |
| debris | 0.528 / 0.571 / 0.549 | 0.667 / 0.694 / 0.680 |
| person | 0.577 / 0.526 / 0.550 | 0.647 / 0.579 / 0.611 |
| noise | 0.581 / 0.481 / 0.526 | 0.651 / 0.788 / 0.713 |

[Confusion-count figure](confusion-matrices.png) and [per-class CSV](per-class.csv)
provide shareable views of these measured counts. Exact train/validation class
distributions and observed-scene counts are in split-class-counts.json.

Full per-class precision/recall/F1/support for every seed and cohort are in
metrics.json; CSV contains seed-0 comparisons. Confusion matrices use rows=true,
columns=predicted, class order wall/doorway/furniture/debris/person/noise in
confusion-matrices.json. Per-environment accuracy and object failure breakdowns
are preserved in metrics.json. Raw per-instance outcomes and model disagreement
cases remain in the ignored experiment directory.

## Dependency baseline and tests

Reused read-only interpreter:
`C:/Users/charv/EchoRescue-pr8-preflight-local/.venv/Scripts/python.exe`.
`PYTHONPATH` points first at this worktree's source packages; `-B` prevents
writing imported package bytecode. No system install, reinstall, policy change,
new deep-learning framework or cloud job was needed.

Python 3.14.4, pytest 9.2.0, numpy 2.5.4, scipy 1.18.1, sklearn 1.9.1,
joblib 1.6.0, pandas 3.1.1, pyarrow 26.0.1, matplotlib 3.11.2,
websockets 17.4, pyserial 3.5; Node 24.19.0, Playwright 1.65.1 and installed Edge.
`pip check` is clean. Prior Windows Application Control DLL errors did not
recur in this run; this does not establish that another machine is unblocked.

- Before edits: Node 41 passed; perception 37 passed, 1 optional Spark skip.
- After edits: perception 47 passed, 1 Spark skip; mapper 20 passed, 1 Windows
  pty/termios skip; bridge 130 passed. No assertion failures or collection blocks.
- Eight synthetic serial-contract cases passed; no hardware port opened.
- Perception emitted 1,091 sklearn parallel-configuration warnings. Tests passed;
  this dependency combination is recorded rather than presented as warning-free.
- Initial baseline command hit six fixture setup errors because the test temp
  parent did not exist. Corrected run passed; those six were not executed tests.

Full XML artifacts: `sonar-ml/data/model-sprint-20261115/*.xml`.

## Demo compatibility and remaining failures

Raw candidate joblib loaded via the existing ForestClassifier; an actual saved
evaluation frame produced valid detections v0.1 and bridge envelope v0.1 with
`source=simulated`, `acquisition_source=simulated`, for baseline and candidate.
No input feature order, public SonarFrame or detection schema changed.

Fresh actual mapper/browser regression: 35 mapper updates, agree -> sonar_closer,
magenta marker, Room analysis of 20,715 points, PNG generation, dense HTTP 200 and
2,230,412-byte binary update; zero browser JS errors. This uses the unchanged
mapper/classifier path, not the trained forest. Ports were checked before launch;
only owned processes were stopped. Browser baseline: 6 assertions pass, 4 fail
(the existing readiness defects). Do not call the baseline a passing demo test.

No-go for an unqualified simulated demo remains:
- Mapper simulation/replay envelope hard-codes live in
  `lidar/mapper/src/lidar_mapper/server.py` lines 159/171. CLI constructs an
  indistinguishable LiveMapper in `__main__.py` lines 97/123.
- `src/mapper-adapter.js:135` independently hard-codes live acquisition/delivery.
- `src/main.js:214` labels all mapper input LiDAR map; line 242 defaults the
  plan's simulated flag to false. Correct backend metadata alone is insufficient.
- `src/main.js:347` preserves disconnected bridge LiDAR only, while lines 356?376
  clear mapper state and return to mock. Reproduction: stream mapper simulation,
  connect Sonar / Preview, stop mapper: Mock data + Connection failed replaces scan.
  It is visibly labeled, not an unlabelled fallback, but loses the last scan.

Exact recommendation for Akshath: preserve mapper's last frame and analysis on
connection loss, clearly label it historical, remove live badge, and clear stale
sonar status. Respect acquisition/delivery in mapper adapter, source badge, saved
capture source and Room analysis simulation flag. For Rishi/Ryan: add delivery
metadata (default live preserves compatibility), select simulated/recorded in the
CLI, and carry original acquisition provenance in recording metadata where known;
unknown replay provenance must not become real/live. Do not change envelope
shape/version merely to replace these existing source values.

No runtime patch was made to these active team files: current databricks-pipeline
also changes the mapper server/CLI and has sonar-interface changes. A backend-only
patch cannot resolve the UI hard-coding safely. Those files, firmware, viewer,
and completed combined worktree were left untouched. Unknown space is never clear.

## Ryan's sonar interface and acceptance check

See ../SONAR_COMPATIBILITY_20261115.md for the exact contract and hardware checklist.
No physical sensor performance, dark operation, iPhone integration on this machine,
or firmware compilation is claimed. The forest needs a 3D point/SNR cloud; a single
HC-SR04 range cannot supply its 26 features or identify objects/people.

## Reproduce in a fresh local environment

From `sonar-ml/` (Windows PowerShell):

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r perception/requirements-sprint-20261115.txt
.venv/Scripts/python.exe -m pip install --no-deps -e 'perception[dev,lakehouse]' -e '../lidar/mapper[dev,sonar]' -e '../websocket-bridge[test,recorded]'
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
.venv/Scripts/python.exe -B -m sonar_perception.experiment --root data/model-sprint-fresh --stage prepare
.venv/Scripts/python.exe -B -m sonar_perception.experiment --root data/model-sprint-fresh --stage evaluate
```

This regenerates all four inputs before training both models on the same locked
holdouts. It refuses existing mismatched inputs and existing results directories;
use a new output root to repeat without deleting artifacts. To generate a separate
candidate dataset only:

```powershell
.venv/Scripts/python.exe -B -m sonar_perception generate --scenes 400 --seed 20261115 --diversity train --no-frames --out data/new-candidate
```

Tests from `sonar-ml/perception`: `../.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider`.
From repo root: `node --test`; run `pytest -p no:cacheprovider` in mapper and bridge
using that interpreter. Prefer a fresh `--basetemp` and `--junitxml` per run.

Windows demo, separate terminals from root after installing packages:

```powershell
node serve.js
sonar-ml/.venv/Scripts/python.exe -u -B -m lidar_mapper sim --frames 80 --serve --sonar-sim --viewer-points 50000
```

Open http://127.0.0.1:4173/, Sonar / Preview, ws://127.0.0.1:8765/ws,
Connect, Room analysis, Download PNG. Sonar must say Simulated sonar. Expect the
known map-label and disconnect defects until team fixes land. Dense map: 8780;
8770 unused by simulation. Browser artifacts and original recovery harness are
preserved under this run's `demo/` and local `.venv/demo-regression.mjs`.

## Next decision

RETAIN BASELINE. Do not deploy this candidate. A later experiment could vary one
augmentation axis at a time or narrow the mounting-height distribution using real
sensor measurements, but that tuning is outside this single-candidate sprint.


Regenerate the confusion figure from repo root (choose a fresh output path):

```powershell
sonar-ml/.venv/Scripts/python.exe -B scripts/render-model-experiment.py --metrics sonar-ml/data/model-sprint-fresh/results/metrics.json --out sonar-ml/data/model-sprint-fresh/confusion.png
```


Actual sprint commands used the previously installed environment without changing it:

```powershell
$py='C:/Users/charv/EchoRescue-pr8-preflight-local/.venv/Scripts/python.exe'
$env:PYTHONPATH='C:/Users/charv/EchoRescue-model-sprint-local/sonar-ml/perception/src'
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
# From sonar-ml/perception; choose a NEW run root when repeating evaluation.
& $py -u -B -m sonar_perception.experiment --root ../data/model-sprint-20261115 --stage prepare
& $py -u -B -m sonar_perception.experiment --root ../data/model-sprint-20261115 --stage evaluate
& $py -B -m pytest -p no:cacheprovider --basetemp ../data/model-sprint-20261115/tests-after --junitxml ../data/model-sprint-20261115/tests-after.xml
```

The shown tests-after path already contains evidence: use a fresh basetemp/XML
name before rerunning tests, since pytest recreates basetemp. The experiment's
existing results are protected by exclusive creation and must be preserved.


## Exact versioned change list

- `scripts/check-sonar-contract.py`
- `scripts/render-model-experiment.py`
- `sonar-ml/docs/decisions/0018-synthetic-acquisition-diversity.md`
- `sonar-ml/docs/log/2026-11-15-backend-model-sprint.md`
- `sonar-ml/docs/reports/SONAR_COMPATIBILITY_20261115.md`
- `sonar-ml/docs/reports/model-sprint-20261115/confusion-matrices.json`
- `sonar-ml/docs/reports/model-sprint-20261115/confusion-matrices.png`
- `sonar-ml/docs/reports/model-sprint-20261115/inputs.json`
- `sonar-ml/docs/reports/model-sprint-20261115/metrics.json`
- `sonar-ml/docs/reports/model-sprint-20261115/model-artifacts.json`
- `sonar-ml/docs/reports/model-sprint-20261115/per-class.csv`
- `sonar-ml/docs/reports/model-sprint-20261115/report.md`
- `sonar-ml/docs/reports/model-sprint-20261115/split-class-counts.json`
- `sonar-ml/docs/status.md`
- `sonar-ml/perception/requirements-sprint-20261115.txt`
- `sonar-ml/perception/src/sonar_perception/__main__.py`
- `sonar-ml/perception/src/sonar_perception/augmentation.py`
- `sonar-ml/perception/src/sonar_perception/dataset.py`
- `sonar-ml/perception/src/sonar_perception/experiment.py`
- `sonar-ml/perception/tests/test_acquisition_diversity.py`
