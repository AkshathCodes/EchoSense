# Research 02 — In-air 3D sonar, sonar ML, simulators, and analogues

_Researched 2026-11-14. Conclusion: no one found combining in-air 3D sonar + ML
for firefighting; the building blocks exist and we are near the research
frontier for in-air 3D ultrasound perception._

## In-air 3D imaging sonar hardware

- **eRTIS** (Univ. Antwerp, CoSys-Lab, Jan Steckel's group): 32-mic pseudo-random (Poisson-disc) MEMS array + NVIDIA Jetson, real-time 3D beamforming; robotics/AGV navigation in harsh settings. Smaller variants: **uRTIS** (5×6 rectangular), **nRTIS** (16 mics, circular, 30 mm aperture). IMU-stabilized steering work in 2024.
  [Ruggedized eRTIS 2025](https://arxiv.org/html/2509.10029v2) ·
  [software guide](https://cosysgit.uantwerpen.be/rtis-software/ertissoftwareusageguide) ·
  [nRTIS](https://arxiv.org/html/2509.01212v1) ·
  [IMU steering](https://arxiv.org/html/2406.06255v1)
- **Calyo Pulse** (commercial): solid-state 3D ultrasound, 40 kHz TX, 32-channel RX, up to 180° FOV depending on range, ~15 m near-range obstacle detection; Sensus SDK gives raw waveforms, **3D point clouds**, 2D intensity; C++ / ROS / Python / Matlab. Eval kit exists; price not found.
  [Uncrewed Systems](https://www.uncrewed-systems.com/?p=12114) ·
  [Starter kit PR](https://www.prweb.com/releases/calyo-introduces-a-starter-kit-for-evaluation-of-high-performance-3d-ultrasound-sensor-302167250.html)

## ML on in-air sonar

- **Antwerp landmark classification (2024)** — [arXiv 2405.19869](https://arxiv.org/html/2405.19869v1): CNN classifies 10 reflector shapes + orientation; **input = cochleograms** (40×106 gammatone time-frequency image of each isolated echo), not point clouds. Range-azimuth imaging only used upstream to detect echoes. **All real data** (no simulation): 10,293 reflector + 46,901 empty samples, 64/16/20 split. 97.3% test accuracy; orientation RMSE ≈ 9.2°. Simple shapes in a lab room, not real objects. 2025 follow-up: multi-label CNN for closely spaced reflectors.
- **Liu et al. 2026, Calyo** — [arXiv 2601.13263](https://arxiv.org/abs/2601.13263): **3D U-Net volumetric segmentation** on in-air ultrasound, labels from LiDAR; authors call it one of the first 3D semantic segmentation demos with in-air ultrasound. Abstract says larger datasets, refined ground truth, weighted losses would help (full metrics in PDF, not checked).
- [Sensors 2019](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6427766/): in-air sonar target classification with neural nets on engineered features.
- **BatVision** — [arXiv 2303.07257](https://arxiv.org/abs/2303.07257): ~55k real chirp-echo samples (binaural, audible band) with synced RGB-D; audio-only depth prediction works. Useful context, **not** drop-in data (wrong band, no array).

## Simulators

- **SonoTraceLab** — [arXiv 2403.06847](https://ar5iv.labs.arxiv.org/html/2403.06847): open-source ray-tracing acoustic model for technical and biological (bat) sonar.
- **SonoTraceUE** — [arXiv 2602.19652](https://arxiv.org/abs/2602.19652) (Feb 2026): Unreal Engine 5 port, hardware ray tracing; **Windows + DirectX 12 GPU only**; reports high correlation with real spectral/spatial data; aimed at synthetic data generation.
- **ACSim** — [GitHub](https://github.com/sollynoay/ACSim): recursive ray-tracing acoustic camera simulator (underwater) with synthetic dataset.
- pyroomacoustics: room impulse responses; not designed for in-air imaging sonar (general knowledge, not verified by search).

## Closest ML analogue: mmWave radar point clouds

Also sparse and noisy.
- [RadHAR](https://github.com/nesl/RadHAR) — activity recognition from radar point clouds; variable points/frame handled by padding or sampling.
- [MiliPoint benchmark](https://doi.org/10.48550/ARXIV.2309.13425) — PointNet++, DGCNN, PointTransformer baselines; a summary reports some plain point-set baselines below 35% on hard tasks ([summary](https://api.emergentmind.com/topics/mmwave-radar-point-cloud-based-har-system)).
- [2024 Applied Sciences](https://doaj.org/article/9024a44f84a0414eb8efcc3e9e9c413a): converting points to **2D pillar images** reached 95.5% — better than plain point models.
- [Light-PointNet + BiLSTM](https://arxiv.org/html/2405.01882v1): multi-frame helps with sparsity.

## Implications for our design (each became an ADR)

| Finding | Design change |
|---|---|
| Sonar ML used dense echo representations; thresholding loses info | Keep **intensity volume + point cloud** ([ADR-0002](../decisions/0002-volume-plus-point-cloud.md)) |
| Ultrasound reflects specularly; flat surfaces vanish at oblique angles; edges/corners bright; soft materials weak | **Specular + occlusion simulation**, not uniform mesh sampling ([ADR-0003](../decisions/0003-specular-simulation.md)) |
| Sonar measures range + angle; angular blur grows with distance | **Spherical-native grid**, blur in angle ([ADR-0004](../decisions/0004-spherical-native-coordinates.md)) |
| Real scans contain many objects | **Segment, then classify** clusters ([ADR-0005](../decisions/0005-segment-then-classify.md)) |
| Plain PointNet struggles on sparse radar; 2D projections do well | **Three baselines** decided by experiment ([ADR-0007](../decisions/0007-model-baselines.md)) |
| Antwerp used only real data | Expect a sim-to-real gap; budget real captures + a labeling tool |
