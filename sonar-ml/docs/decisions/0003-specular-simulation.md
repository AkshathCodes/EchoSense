# ADR-0003: Simulate specular reflection and occlusion

- **Status:** accepted (corrects the 2026-11-13 plan)
- **Date:** 2026-11-14
- **Area:** perception

## Context
The first plan was: sample 3D meshes (ModelNet/ShapeNet) uniformly, then add
noise, blur, dropout, and ghost points. But ultrasound at ~40 kHz (λ ≈ 8.6 mm)
reflects mostly **specularly** off building-scale surfaces:
- a flat wall echoes back only near normal incidence — at oblique angles it largely disappears;
- edges and corners (diffraction, corner-reflector geometry) are bright;
- soft/absorbent materials (people, fabric) return weak echoes;
- nearer surfaces occlude farther ones.

A uniformly sampled mesh would teach the model shapes the sensor never sees.

## Decision
`sim/acoustics.py` computes, per surface sample:
1. **Visibility**: in FOV and range; occlusion via an angular z-buffer (nearest wins per fine az/el cell).
2. **Specular weight**: `cos(θ)^p` where θ is the angle between the surface normal and the direction to the sensor, with a floor for diffuse scatter.
3. **Edge bonus** for samples flagged as edges/corners.
4. **Material reflectivity** per class.
5. **Two-way spreading + air absorption** (`α` dB/m, higher in smoke).
6. **Temperature**: true sound speed from air temperature vs. the sensor's assumed speed rescales measured range.
7. **Multipath ghosts**: weak spurious returns behind real ones, labeled noise.
8. **Turbulence jitter** in range and angle.
Then `grid.py` rasterizes and blurs in spherical coordinates (ADR-0004).

## Alternatives considered
- Uniform mesh sampling + noise — wrong physics (above).
- SonoTraceUE / SonoTraceLab — far more realistic, but SonoTraceUE needs Windows + DX12 GPU, and integration time is significant. **Revisit** if a teammate has the machine; our `SensorSource` interface makes it a drop-in.

## Refinement (2026-11-14)
"Oblique walls vanish" holds only for surfaces too small to contain their
specular point. A large wall stays bright wherever the perpendicular from the
sensor lands on it; walls parallel to the line of sight and small panels turned
away are what fade. Verified in `tests/test_acoustics.py`; see log §9.

## Consequences
- Primitive shapes (boxes, cylinders, spheres) only, for now — no mesh library dependency. Mesh support can come later via the same sample-with-normals format.
- All physics parameters are guesses until validated against real captures. Treat them as augmentation ranges, not truth.
