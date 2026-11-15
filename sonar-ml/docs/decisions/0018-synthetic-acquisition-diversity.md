# ADR-0018: Opt-in acquisition diversity, controlled forest experiment

- **Status:** accepted for experimentation; candidate promotion rejected
- **Date:** 2026-11-15
- **Area:** perception

## Context

The available trainable forest uses fixed-height XYZ/SNR features and simulated
material responses. Room analysis is a separate deterministic JavaScript model.
PR #8 and databricks-pipeline share the same perception package; no merge is needed.
No production forest weights or real array-sonar dataset were available locally.

## Decision

Preserve default generation and deployed inference. Add one opt-in profile for
height/material/pitch/range/missed-detection diversity, with a separate RNG stream.
Use common scene splits and fixed, independently seeded standard/challenge holdouts.
Train the unchanged 300-tree balanced RF across three seeds; preserve every model.
Require limited nominal regression and person-recall regression before adoption.

The candidate increases challenge macro-F1 by .0996 but decreases standard by
.0556; standard person end-to-end recall decreases .0308. Retain the baseline.
Measured inputs, metrics, confusion matrices and commands are in
[the experiment report](../reports/model-sprint-20261115/report.md).

## Alternatives considered

- Change live Room analysis or integrate this RF: would modify team-owned UI and
  confuse different label sets/sensors; not authorized for production inference.
- Tune multiple models/profiles on the holdout: invalidates a single controlled
  experiment and risks test-set overfitting.
- Circumvent Windows policy or replace package DLLs: unnecessary; standard
  imports/tests succeeded in the reused environment, without policy changes.

## Consequences

Default behavior and public schemas stay compatible. The profile is an opt-in
stress-test tool, not calibrated hardware physics. Further calibration requires
real captures. Candidate weights stay local and are not deployed. Provenance and
disconnect UI fixes remain recommendations for their owners, not changes here.
