# Contributing

## Branches and PRs

- `main` should always run: `cd sonar-ml/perception && pytest` and `node --test` (repo root) pass.
- The team currently works on `main` in the EchoSense monorepo. If you branch, prefix by area: `perception/…`, `hw/…`, `fw/…`, `viewer/…`, `docs/…`.
- Small PRs. One reviewer from the owning sub-team.
- PR description: what changed, how you tested it, which docs you updated.

## Documentation is part of the change

A PR is not done until the relevant docs are updated:

| You changed… | Update… |
|---|---|
| The `SonarFrame` format or any cross-team contract | `docs/interfaces/*` (bump version) + an ADR |
| A design choice someone may question | new ADR in `docs/decisions/` |
| What works / what's next | `docs/status.md` |
| Anything you tried, especially if it failed | `docs/log/<date>-<topic>.md` |
| A new source or prior-art finding | `docs/research/*` |

## Conventions

- Dates are absolute (`2026-11-14`), never "yesterday".
- Units are SI (meters, seconds, °C, Hz). Angles in code are radians; in docs, say which.
- Sensor frame: **x forward, y left, z up**, origin at the sensor. Azimuth positive to the left; elevation positive up.
- Data files go in `data/` (git-ignored). Commit small fixtures only, under `perception/tests/fixtures/`.

## Per-area notes

- **perception:** Python ≥ 3.10, numpy-first, torch optional. Add a test for any new pipeline stage.
- **hardware / firmware:** document the sensor geometry (mic positions, beam width, chirp) in `docs/interfaces/sensor-geometry.md` — perception needs it.
- **viewer (repo root `src/`):** consume `SonarFrame` files or the detections JSON; don't reimplement processing.
