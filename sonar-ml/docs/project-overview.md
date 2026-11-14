# Project overview

_Last updated 2026-11-14._

## Problem

In a structure fire, smoke can drop visibility to near zero. Firefighters
search by touch and with thermal imaging cameras (TICs). TICs see through
smoke but have known limits: they cannot see through walls, floors, or people;
glass, tile, and polished metal confuse them; lenses fog; firefighters who lose
the camera can become disoriented; and over-reliance is a training concern.
Camera-based object detection (RGB) is useless in dense smoke.

## Idea

Use **ultrasonic sonar** — which does not depend on light or heat contrast —
to build a coarse **3D map** of the space ahead, then **segment** it into
objects and **classify** each (wall, doorway, furniture, debris,
person-sized object). Output to a demo view now, and conceptually to
audio/haptic cues for a firefighter later.

## Scope for MadHacks

**In scope (software, now):**
1. A hardware-agnostic data contract (`SonarFrame`)
2. A physics-informed sonar **simulator** to generate labeled training data
3. 3D mapping: rasterize returns into a spherical intensity volume + point cloud
4. Segmentation (clustering) into object candidates
5. Classification of each candidate, with embeddings; non-deep baseline + deep models
6. Evaluation by degradation level; a viewer

**In scope (later, as hardware arrives):** a live sensor driver, real data
capture, fine-tuning on real data, fog/warm-air tests, camera comparison.

## Non-goals / explicitly cut

- **Predicting fire behavior** (flare-up, flashover). Sonar cannot measure
  combustion; this would need temperature/gas sensors and data we don't have.
  See [ADR-0006](decisions/0006-defer-fire-prediction.md).
- **Claiming victim detection.** We classify *person-sized objects*. Breathing
  micro-motion detection is a stretch idea, unvalidated.
- **Real-fire testing.** Demos use fog machines / warm air at safe distances.

## Stretch ideas (kept, not committed)

- **Search-priority heuristic:** rank likely victim locations from layout and
  object classes (near doors, bedrooms, low to floor). Must be labeled as
  guidance, not detection.
- **Temperature from time-of-flight drift:** speed of sound depends on air
  temperature, so drift over a known reflector path is a crude thermometer
  ("air ahead is getting hotter"). Doubles as a range correction.
- **Multi-frame stacking** for denser maps and micro-motion (breathing).

## Pitch (draft)

> A sonar-based vision system that maps and identifies objects through smoke,
> built so the sensing hardware can be swapped without changing the AI.

Differentiators vs. existing tech: works where thermal struggles (reflective
surfaces, fogged optics); cheap, light, low power; non-visual output avoids the
weight/fit issues reported with AR helmets. See
[research/01-firefighter-landscape.md](research/01-firefighter-landscape.md).

## Team areas

perception (this repo's `perception/`), hardware, firmware, app/demo. See the
root [README](../README.md).
