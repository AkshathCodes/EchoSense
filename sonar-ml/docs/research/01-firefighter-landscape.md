# Research 01 — What exists for firefighters in low visibility

_Researched 2026-11-13 via web search. Mostly news, government pages, and papers;
treat details as a first pass. Sources at the bottom of each section._

## Thermal imaging cameras (TICs) — the standard tool

See through smoke, but:
- Cannot see through walls, floors, or people.
- Glass, mirrors, tile, linoleum, polished metal interfere (reflections).
- Emissivity differences make temperature readings easy to misread.
- Fogged facepieces/lenses degrade the image; one analysis found crews wiped facepiece and display but not the TIC lens.
- Losing the camera can cause immediate disorientation; over-reliance is a recognized training issue.
- Cannot see hidden trusses.

Sources: [Fire Engineering](https://www.fireengineering.com/firefighting/thermal-imaging-camera/),
[Fire Apparatus](https://fireapparatusmagazine.com/?p=135187),
[Firehouse — Five Don'ts](https://www.firehouse.com/article/10464218/five-donts-of-thermal-imaging),
[USFA EFO paper](https://apps.usfa.fema.gov/pdf/efop/efo32815.pdf),
[FSRI](https://fsri.org/program-update/tactical-considerations-web-series-ep-12-thermal-imaging-limitations-structural).

## Qwake Technologies C-THRU — closest commercial product

- Helmet-mounted AR display overlaying thermal-derived edge outlines of objects.
- Navigator helmet unit + Visual Command tablet for incident commander; mayday alerts.
- DHS S&T opened department testing July 2024; field assessment found better navigation but **weight balance and fit discomfort**.
- 2026: Colorado Springs one of 10 test cities; Orange County FL among 80 departments.
- Still camera/thermal-based → shares TIC limits.

Sources: [DHS feature](https://www.dhs.gov/science-and-technology/news/2023/11/06/feature-article-picturing-future-firefighting),
[Firehouse — DHS testing](https://www.firehouse.com/tech-comm/press-release/55093731/dhs-opens-testing-for-c-thru-navigation-device-for-firefighters),
[Fire & Safety Journal — San Diego assessment](https://fireandsafetyjournalamericas.com/dhs-assesses-qwake-technologies-c-thru-device-at-san-diego-fire-rescue-training-center/),
[Axios Colorado Springs](https://www.axios.com/local/colorado-springs/2026/05/29/ar-firefighter-helmets-test-colorado-spring),
[Fox 35 Orange County](https://www.fox35orlando.com/news/orange-county-firefighters-test-augmented-reality-helmets-smoke-filled-rescues),
[USFA blog](https://www.usfa.fema.gov/blog/c-thru-new-system-for-situational-awareness-in-low-visibility/).

## Indoor location tracking (NIST PSCR) — where people are, not what's around them

- UC Irvine infrastructure-free localization: 3–4 perimeter beacons + wearable unit; position + bearing for zero-visibility directional commands.
- Oxford IPSER: thermal, inertial, mmWave radar for tracking/mapping.
- First Responder Smart Tracking (FRST) challenge, NIST "Dots" test facility.

Sources: [NIST infrastructure-free](https://www.nist.gov/communications-technology-laboratory-ctl/pscr/infrastructure-free-localization-system-firefighters),
[NIST thermal/inertial/radar](https://www.nist.gov/ctl/pscr/real-time-first-responder-tracking-and-mapping-thermal-intertial-and-radar),
[Critical Comms — FRST](https://www.criticalcomms.com.au/content/research/news/nist-research-into-indoor-tracking-for-first-responders-1245810308).

## Sensing through smoke — research

**Radar is strongest.** A Fire Technology study of 11 rangefinders/cameras in smoke: radar and IR cameras outperformed; in large-scale tests IR stereo and radar located targets within 10% and 1% regardless of visibility; **LIDAR errors appeared below ~4 m visibility**.
[Sensor fusion concept paper](https://ouci.dntb.gov.ua/works/4NQnB027) proposes thermal IR + FMCW radar + ultrasonic.

mmWave: Shibaura (2005–06) mmWave radar + gyro → 3D maps of smoke-filled rooms
([SPIE](https://proceedings.spiedigitallibrary.org/conference-proceedings-of-spie/6051/60510L/The-support-system-of-firefighters-by-detecting-objects-in-smoke/10.1117/12.649448.full));
[Bystrov et al., Sensors 2021](https://doaj.org/article/fd67cb2be84142d39ceb18179e451add) tested 79 GHz and 300 GHz radar in real fires — promising.

**Sonar / ultrasound — tried, fire distorts it:**
- UT Austin: off-the-shelf ultrasonic rangefinders **could not penetrate flames** → moved to **pulse-compression sonar** ([thesis](https://repositories.lib.utexas.edu/handle/2152/28675?show=full)); later parametric array imaged walls through moderate flames ([phys.org](https://phys.org/news/2012-10-zeroing-science-propagation.html), [ASA](https://acoustics.org/pressroom/httpdocs/164th/Abbasi_2pPA14.html)).
- [Sensors 2018 guided vehicle](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6308595/): hot smoke and soot distort ultrasonic propagation; ToF / phase / amplitude ranging methods.
- [Lafayette student harness prototype](https://sites.lafayette.edu/euler/?p=559): two chest-height ultrasonic sensors.
- [WPI bat-inspired drones, Apr 2026](https://electronics360.globalspec.com/article/23562/bat-inspired-ultrasound-lets-palm-sized-drones-navigate-through-fog-smoke): ultrasound + AI through fog/smoke, 72–100% success over 180 runs; **struggled with thin objects** (poles, branches).
- Most firefighting robots use basic ultrasonic sensors only for obstacle avoidance ([ScholarHub](https://scholarhub.vn/publication/An-ultrasonic-obstacle-avoidance-system-for-fire-fighting-robot/feb934d7-e7c7-4577-9c9d-93f73d0a60ce), [IJRA](https://ijra.iaescore.com/index.php/IJRA/article/download/20712/13091)).
- Patent: [ultrasonic beacon tracking for firefighters](https://patents.google.com/patent/US6826117).

## Takeaways (gaps we target)

1. No deployed **wearable sonar** for firefighters found — sonar work is academic / student prototypes.
2. Thermal's blind spots (reflective surfaces, fogged optics) are where acoustics helps.
3. **Heat/soot distortion is the main technical risk** → chirps / pulse compression, temperature compensation, test with heat gun / fog machine.
4. Output modality matters (C-THRU weight/fit complaints) → audio/haptic differentiator.
5. Sensor fusion (sonar + IMU or thermal) matches what fusion papers propose.

## Not covered / unverified
- Haptic navigation devices, other commercial smoke-sensing products, ultrasound startups for firefighters.
- No confirmed radar product on the market; no independent sonar-in-real-fire performance numbers.
