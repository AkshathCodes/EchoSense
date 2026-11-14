# data/

Local datasets. Contents are git-ignored (only this README is tracked).

Suggested layout:

```
data/
  synthetic/<version>/     # output of `python -m sonar_perception generate`
  recorded/<date>-<place>/ # real captures from the sensor, as SonarFrame .npz files
```

Every dataset folder should contain a `manifest.json` describing how it was
made (generator version, config, seed, conditions). The generator writes one
automatically. For real captures, write it by hand: date, location, sensor
version, temperature, smoke/fog conditions, what objects were present.

Share large datasets through a shared drive, not git; record the link in
`docs/status.md`.
