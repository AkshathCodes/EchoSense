# ADR-0012: Improving person detection: spherical clustering, SNR intensity, more data, person bias

- **Status:** accepted
- **Date:** 2026-11-14
- **Area:** perception (changes `SonarFrame` to format 0.2)

## Context
v2 reported person recall of 0.67 **per cluster**. A new end-to-end tool
(`diagnose`) that follows every real person showed only **43%** were detected
correctly:

| Outcome (v2) | Share | Worst |
|---|---|---|
| never detectable | 27% | lying 46%, beyond 4 m 48%, heavy 58% |
| merged into a neighbor | 14% | clear air 25% |
| misclassified | 16% | crouching → furniture 25%, lying → debris 19% |
| correct | 43% | standing 59% |

## Decision
1. **Cluster in spherical coordinates** (`range, az·2, el·2`, eps 0.12, about one
   beam width) instead of xyz with eps 0.25 m. Person merges fell from 23% to
   13% in a sweep, with no extra fragmentation. Plain xyz with a smaller eps
   shattered far objects (5× more clusters).
2. **Point intensity = SNR** (amplitude ÷ frame noise floor). A peak-normalized
   value depends on whatever bright surface is in view; absolute amplitude
   varies too much between scenes. SNR is what CFAR-style processing gives on
   real hardware. `SonarFrame` format bumped to 0.2.
3. **9 more shape features** (vertical width profile, head-sized top, density,
   intensity-height correlation, main-axis orientation). Measured gain is small
   (+1.3 points accuracy, +0.4 person recall), but they're kept.
4. **Default training size 2,000 scenes** (about 6 min to generate).
5. **Recommend `--bias person=2`** for the demo and any firefighter-facing
   output. A missed person costs far more than a false alarm. **Not** the code
   default: it's a product decision for the team.
6. **Points reported in the level body frame**, with `SensorConfig.tilt_deg`
   for a downward-tilted sensor (so tilt can be studied and real IMUs used).

## Results (synthetic; 400 fresh scenes for end-to-end, 3 seeds for cluster metrics)

| | v2 baseline | v3, 600 scenes | v3, 2,000 scenes | **v3, 2,000 + bias 2** |
|---|---|---|---|---|
| People detected correctly, end to end | 43% | 45% | 47% | **53%** |
| Merged | 14% | 9.6% | 9.6% | 9.6% |
| Misclassified | 16% | 18% | 16% | **9.6%** |
| Never detectable | 27% | 27% | 27% | 27% |
| Person precision (cluster) | – | – | – | 0.76 |
| Lying people correct | 18% | 6% | 6% | 20% |
| False object detections from noise | ~0.14/frame | ~0.08/frame | – | 0.02/frame |
| Cluster accuracy (6 classes) | 0.870 | 0.834 | 0.853 ± 0.005 | – |

Cluster accuracy is lower than in v2 because the class mix changed: spherical
clustering leaves far fewer, harder noise clusters (41% → 9% of clusters). The
false-detections-per-frame row is the honest comparison.

**Tilt 15°** made more lying people visible (undetectable 46% → 37%) but not
more correctly classified overall (44% vs 45% at 600 scenes). It remains a
hardware recommendation for floor-level coverage, not a fix by itself.

## Consequences and the ceiling
- **27% of people are never detectable and 10% merge**, so about 63% is the
  ceiling for any classifier on this simulated sensor. We're at 53%.
- **Lying people are the weak spot (20%).** From chest height the sensor sees a
  fragment that looks like debris. Since victims are often on the floor, this
  matters. Options: lower or handheld mounting, a sweep motion (multi-frame),
  more tilt, or a person-on-floor-specific model.
- The remaining gains are in **sensing** (signal-to-noise, coverage,
  resolution) and **multi-frame** methods, not in classifier tuning.
