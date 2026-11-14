# Interface: detections (v0.1)

_Output of perception, input to the app/demo team. Code:
`perception/src/sonar_perception/detections.py`._

One JSON file per frame, written by
`python -m sonar_perception detect ... --out <dir>` as
`<dir>/detections_<NNNNN>.json`, plus `<dir>/summary.json`.

Coordinates and units follow [sonar-frame.md](sonar-frame.md): sensor frame,
x forward, y left, z up, meters. **Angles in this file are degrees** (friendlier
for UI); the frame file uses radians.

## Schema

```json
{
  "format_version": "0.1",
  "frame": {
    "timestamp": 12.0,
    "source": "synthetic",
    "sensor_id": "sim-v0",
    "scene_id": 12,
    "conditions": "fog",
    "n_points": 4821
  },
  "model": "random_forest_features",
  "detections": [
    {
      "id": 0,
      "class": "person",
      "class_id": 4,
      "confidence": 0.82,
      "probs": {"wall": 0.01, "doorway": 0.0, "furniture": 0.12, "debris": 0.05, "person": 0.82, "noise": 0.0},
      "centroid": [2.41, -0.37, -0.65],
      "range_m": 2.55,
      "azimuth_deg": -8.7,
      "elevation_deg": -14.8,
      "bbox_min": [2.20, -0.61, -1.31],
      "bbox_max": [2.63, -0.12, 0.18],
      "n_points": 212,
      "mean_intensity": 0.18,
      "gt_class": "person"
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `class` / `class_id` | Predicted class. Ids: 0 wall, 1 doorway, 2 furniture, 3 debris, 4 person (*person-sized object*), 5 noise |
| `confidence` | Probability of the predicted class (uncalibrated) |
| `probs` | All class probabilities |
| `centroid`, `bbox_min`, `bbox_max` | Meters, sensor frame, axis-aligned |
| `range_m`, `azimuth_deg`, `elevation_deg` | Centroid in spherical form: what an audio or haptic cue needs ("person, 2.5 m, slightly right") |
| `gt_class` | Only on labeled (synthetic) frames, for evaluation; never present on live data |

Detections predicted as `noise` are left out unless `--include-noise` is passed.
They are sorted by range, nearest first.

## Versioning
Bump `format_version` on breaking changes and tell the app team.
