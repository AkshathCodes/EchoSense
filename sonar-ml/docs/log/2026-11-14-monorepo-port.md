# 2026-11-14 (session 5) — Port into the EchoSense monorepo

_Goal from the lead: move everything from the standalone `madhacks-sonar` repo
into the team monorepo `EchoSense` (AkshathCodes/EchoSense), on `main`._

## Decisions (from the lead)
- Everything goes under **`sonar-ml/`**; the web viewer stays at the repo root
  and `acoustic/` is untouched.
- Our empty `app/` placeholder was dropped: the root web viewer is the app.
- Old repo `Rishi-S20/madhacks-sonar` and `~/Desktop/madhacks-sonar` are left
  as-is (backup, and they hold the 1.7 GB of generated data and the venv).
- Overlap with `acoustic/` is **documented only** (docs/status.md "Relation to
  the rest of EchoSense"); no code changes to other teams' files.

## What changed
- Copied all tracked files (code, tests, docs, ADRs, logs) into `sonar-ml/`.
  Not copied: `.venv/`, `data/*`, `runs/`. Regenerate data with `generate`.
- Paths: all commands now run from `sonar-ml/` (venv at `sonar-ml/.venv`).
  Relative doc links were unaffected. Older logs still say "repo root" for
  what is now `sonar-ml/`; read them that way.
- Added a root `AGENTS.md`/`CLAUDE.md` and a root README section pointing here.
