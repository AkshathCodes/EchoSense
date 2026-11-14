# 2026-11-14 (session 3) — Improving person recall

_Goal from the lead: "Improve person recall." Decision record:
[ADR-0012](../decisions/0012-person-recall.md)._

## 1. Measure end to end first
- Added per-object metadata to frames (`meta.object_list`: name, class,
  variant such as pose or furniture kind) and `diagnostics.py` /
  `python -m sonar_perception diagnose`.
- **The reported 0.67 recall was per cluster.** Following every person, only
  **43%** were detected correctly. The rest: 27% never detectable, 14% merged
  into a neighbor, 16% misclassified (crouching → furniture, lying → debris).
- Lesson: per-cluster metrics ignore everything segmentation already lost.
  AGENTS.md rule 7 now says to quote end-to-end numbers.

## 2. Merges → spherical clustering
- Sweep on 150 scenes (person own / merged / fragmented; total clusters):
  - xyz eps 0.25 (old): 0.77 / 0.23 / 0.00; 539 clusters
  - xyz eps 0.18: 0.84 / 0.15 / 0.01; **2,837** clusters (far objects shatter)
  - xyz eps 0.12: 0.65 / 0.06 / **0.29**; 17,166 clusters
  - spherical ang 2.0, eps 0.12: **0.87 / 0.13 / 0.00; 628 clusters** ← chosen
- Why it works: sonar resolution is angular, so the neighborhood should be too
  (same reasoning as ADR-0004).

## 3. Misclassification → features, intensity, bias
- Added 9 shape features. Ablation on v3 data (3 seeds): all 26 features 0.834 /
  person 0.703; original 17 features 0.821 / 0.699. **Small gain.**
- **Wrong turn: absolute intensity.** Switched point intensity from
  peak-normalized to absolute amplitude. Noise recall dropped from 0.94 to
  0.78, which I blamed on the intensity change, so I switched to SNR. Noise
  recall stayed about 0.80. The ablation showed the real cause:
  **spherical clustering cut noise clusters from 1,384 to 242**, leaving fewer,
  harder ones. False detections from noise actually fell (~0.14 → ~0.08 per
  frame). Kept SNR intensity anyway because it's the physically right choice.
- **Person bias** (multiply the person probability, renormalize):

  | bias | end-to-end correct | person precision | person recall (cluster) |
  |---|---|---|---|
  | 1 | 45% | – | 0.70 |
  | 1.5 | 48% | 0.76 | 0.85 |
  | 2 | 51% | 0.70 | 0.86 |
  | 3 | 56% | 0.60 | 0.88 |

  (600-scene model, tilt 0.)

## 4. Invisible → tilt (hardware question)
- Implemented `SensorConfig.tilt_deg`. The scene is simulated in the tilted
  sensor frame and points are rotated back to the level body frame.
- Tilt 15°: undetectable lying people 46% → 37%, but overall end-to-end 42%
  vs 45%: the newly visible lying people get called debris. With bias 2 both
  tilts are about 51%. Keep it as a hardware recommendation for floor coverage.

## 5. More data
- 2,000 scenes (8,881 clusters, 1,353 person): cluster accuracy 0.853 ± 0.005,
  person cluster recall 0.73. End to end: **47%** without bias, **53%** with
  bias 2 (precision **0.76**, up from 0.70 at 600 scenes). Noise false
  detections: 4 in 200 frames.

## 6. Where it stands
- End-to-end person detection **43% → 53%** (synthetic). Ceiling ≈ 63%,
  because 27% are never detectable and ~10% merge.
- **Lying people: 20%** at best. This is the most important open problem for
  the pitch.
- Next levers are sensing and multi-frame, not classifier tuning. See status.md.
