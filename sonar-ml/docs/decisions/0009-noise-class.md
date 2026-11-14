# ADR-0009: A cluster-level `noise` class

- **Status:** accepted
- **Date:** 2026-11-14
- **Area:** perception (changes the class list, so it's an interface change)

## Context
Clusters made mostly of ghost or noise points were dropped from training. At
inference time the classifier would have had to force every such cluster into a
real class: a ghost becomes a "person". With the noise-aware threshold
(ADR-0008) the v0 data had only 3 noise clusters, too few to learn from, though
real data will have many more.

## Decision
- Add class `5 noise` at the **cluster** level. Point labels keep `-1` for
  noise/background (`NOISE`), and a cluster whose majority point label is `-1`
  gets `NOISE_CLASS = 5`.
- To get realistic numbers of noise clusters, `dataset.generate` draws the
  detection thresholds per scene (`threshold_jitter`, on by default). A first
  range (noise margin 6-18 dB) made 64% of clusters noise; narrowed to
  10-18 dB, about 20%.
- `detect` drops `noise` predictions by default (`--include-noise` keeps them).

## Consequences
- 6 classes. Noise recall is about 0.98 for the random forest on v1.
- `docs/interfaces/detections.md` lists the class ids. The app team must ignore
  `noise`, or show it as "uncertain".
- Threshold jitter also makes the classifier less sensitive to one threshold
  setting, which helps when real hardware has its own.
