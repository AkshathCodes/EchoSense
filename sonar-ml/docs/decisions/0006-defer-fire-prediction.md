# ADR-0006: Cut fire-behavior prediction; reframe "people prediction"

- **Status:** accepted
- **Date:** 2026-11-13
- **Area:** project

## Context
The original idea included (a) a model predicting whether fire is about to
intensify and (b) predicting where people could be.

## Decision
- **(a) Cut.** Sonar cannot sense combustion. Flare-up prediction needs
  temperature, gas, and airflow data we can't collect; judges and firefighters
  would rightly distrust it. *Kept, reframed:* speed-of-sound drift as a coarse
  "air ahead is getting hotter" indicator (stretch).
- **(b) Reframed** as a **search-priority heuristic** from layout and object
  classes, always labeled as guidance, never as detection (stretch).
- The core is **detect + classify objects through smoke**.

## Consequences
Every claim in the pitch ties to something the hardware measures.
