# ADR-0001: Hardware-agnostic `SonarFrame` interface

- **Status:** accepted
- **Date:** 2026-11-13
- **Area:** project

## Context
Hardware design is undecided (pan-tilt vs. mic array vs. buying a kit), but the
software team wants to start now. Hardware choices change the signal processing
heavily, the 3D map moderately, and the classifier barely — *if* the
classifier's input format is fixed.

## Decision
Fix the seam at a `SonarFrame` (intensity volume + point cloud + metadata).
Everything upstream is a swappable `SensorSource` (synthetic, recorded, live).
Everything downstream depends only on `SonarFrame`. Hardware-dependent values
(FOV, resolution, beam width, range) are **config**, not constants.

## Alternatives considered
- Wait for hardware — wastes the build window.
- Build directly against a guessed sensor — rewrite when hardware changes.

## Consequences
- Perception, app, and hardware can work in parallel.
- Main remaining coupling: train/live data mismatch. Mitigate with broad
  augmentation and fine-tuning on real captures.
- Contract changes need a version bump + doc + ADR.
