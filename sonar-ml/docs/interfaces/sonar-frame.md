# Interface: `SonarFrame` (v0.2)

_The contract between any sonar source (real or simulated) and everything downstream._
Code: `perception/src/sonar_perception/frame.py`.

## Coordinate frame

- Origin at the sensor's acoustic center.
- **x forward, y left, z up** (right-handed).
- **`points` are in the level body frame**: if the sensor is tilted (`meta.tilt_deg`,
  from mounting or an IMU), points are rotated back so z is truly up. The
  `volume` and `grid` stay in the (possibly tilted) sensor frame. Added in 0.2.
- Azimuth `az = atan2(y, x)`, positive to the left. Elevation `el = asin(z / r)`, positive up.
- Angles in **radians** in code and files. Distances in **meters**.

## Fields

| Field | Type / shape | Required | Meaning |
|---|---|---|---|
| `timestamp` | float (s) | yes | Capture time (sim: frame index) |
| `grid` | `SphericalGrid` | yes | Bin edges: `range_edges [R+1]`, `az_edges [A+1]`, `el_edges [E+1]` |
| `volume` | float32 `[R, A, E]` | yes | Beamformed echo intensity per (range, az, el) bin, linear units, ≥ 0 |
| `points` | float32 `[N, 4]` | yes | Point cloud: `x, y, z, intensity`, derived from `volume` by thresholding. **intensity = SNR** (amplitude ÷ frame noise floor, estimated as the volume median). In 0.1 it was amplitude ÷ frame peak |
| `meta` | dict (JSON-serializable) | yes | See below |
| `point_labels` | int16 `[N]` | sim / labeled only | Class id per point (`-1` = noise) |
| `point_instances` | int32 `[N]` | sim / labeled only | Object instance id per point (`-1` = noise) |

### `meta` keys

| Key | Meaning |
|---|---|
| `source` | `"synthetic"`, `"recorded"`, `"live"` |
| `sensor_id` | Free text, e.g. `"sim-v0"`, `"proto-array-1"` |
| `format_version` | `"0.2"` |
| `tilt_deg` | Sensor pitched down by this angle (0 = level) |
| `object_list` | (sim only) per-instance metadata: name, class, variant (e.g. person pose), position. Index = instance id |
| `speed_of_sound_assumed` | m/s used to convert time-of-flight to range |
| `temperature_c` | Measured air temperature if available, else `null` |
| `conditions` | Free text / dict: clear, fog, warm, smoke level |
| `scene_id` | (sim / datasets) id for split-by-scene |

## File format

One frame per `.npz` (`numpy.savez_compressed`) with arrays
`volume, points, range_edges, az_edges, el_edges, timestamp, [point_labels, point_instances]`
and `meta` stored as a JSON string. Use `SonarFrame.save()` / `SonarFrame.load()`.

## Changelog
- **0.2** (2026-11-14): intensity is SNR (was peak-normalized); points in the level body frame; `tilt_deg`; sim `object_list`. Readers accept 0.x.
- **0.1** (2026-11-14): initial.

## Versioning

Bump `format_version` on any breaking change, update this doc, and add an ADR.
Readers should reject unknown major versions.

## Why both a volume and points?

Thresholding to points discards information; published in-air sonar ML used
denser representations (time-frequency echo images, volumetric U-Nets).
Points are convenient for clustering and display. See
[ADR-0002](../decisions/0002-volume-plus-point-cloud.md).
