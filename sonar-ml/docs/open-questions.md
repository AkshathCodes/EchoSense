# Open questions

_Add questions as you hit them; move answered ones to the bottom with the answer and a link._

## Hardware
- Pan-tilt scan, static mic array, or buy a Calyo Pulse eval kit? (cost, lead time unknown)
- Which ultrasonic-capable MEMS mics, and what's their response at 40 kHz+?
- Achievable angular resolution with our aperture? This decides whether classes are separable at all — test early with two distinct shapes.

## Perception
- **People lying on the floor: 32-35% after ping averaging and sweep (ADR-0013).** What's left is mostly physics. Would a lower or handheld scan, a lower frequency, or more power close the gap?
- Can the firmware actually average 4 pings at an acceptable frame rate, and is the wearer still enough?
- What person bias should the product use? `person=2` gives 53% detection at 0.76 precision; that's a team/product decision.
- How do we split doorways from the walls they're set in? DBSCAN merges them (v2).
- Will deep models overtake the random forest with ≥1,500 scenes or multi-frame input?
- How much of the extreme-condition failure is the sensor's physics (range) and how much is the classifier?
- How large is the sim-to-real gap? Prior in-air sonar classification (Antwerp) used only real data.
- Should we switch the simulator to SonoTraceUE (physics ray tracing; Windows + DX12 GPU) once someone has the machine?
- Is single-frame enough, or do we need multi-frame stacking for usable density?
- Is a "person-sized" class distinguishable from furniture at our resolution? Material reflectivity is our main cue in sim — unvalidated.

## Product / pitch
- Output modality: audio, haptic, or visual? Gloves + SCBA + noise constrain all of them.
- What do actual firefighters want? Try to talk to one (local department, UW–Madison connections).

## Unverified research items
- No independent performance numbers found for sonar in real fires.
- Haptic navigation devices / other ultrasound startups for firefighters were not searched.
- Calyo Pulse price and availability not found.

## Answered
- **Which baseline wins on synthetic data?** The random forest on hand-crafted features (v1 and v2, 3 seeds). See [ADR-0011](decisions/0011-model-choice-v2.md). Revisit with more data.
- **Does the floor flood the point cloud?** No, only 2-4% of points at chest height with ±30° elevation ([ADR-0010](decisions/0010-simulator-realism-v2.md)).

## Hardware requirements found in simulation
- Tilt the sensor down 10-20° or widen elevation; floor-level objects within ~2.2 m are otherwise out of view.
- Range collapses at high absorption (extreme preset: about 6× fewer detectable objects). Frequency, power and chirp length trade against this.
