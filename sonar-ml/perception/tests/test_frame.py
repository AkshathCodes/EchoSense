import numpy as np
import pytest

from sonar_perception.config import SensorConfig
from sonar_perception.frame import FORMAT_VERSION, SonarFrame


def _frame(n=10, labels=True):
    grid = SensorConfig().grid()
    return SonarFrame(
        timestamp=1.5,
        grid=grid,
        volume=np.random.rand(*grid.shape).astype(np.float32),
        points=np.random.rand(n, 4).astype(np.float32),
        meta={"source": "synthetic", "conditions": {"name": "clear"}},
        point_labels=np.zeros(n, np.int16) if labels else None,
        point_instances=np.zeros(n, np.int32) if labels else None,
    )


def test_roundtrip(tmp_path):
    f = _frame()
    f.save(tmp_path / "f.npz")
    g = SonarFrame.load(tmp_path / "f.npz")
    assert g.timestamp == f.timestamp
    assert g.meta["format_version"] == FORMAT_VERSION
    np.testing.assert_allclose(g.volume, f.volume)
    np.testing.assert_allclose(g.points, f.points)
    np.testing.assert_array_equal(g.point_labels, f.point_labels)


def test_roundtrip_unlabeled(tmp_path):
    f = _frame(labels=False)
    f.save(tmp_path / "f.npz")
    assert SonarFrame.load(tmp_path / "f.npz").point_labels is None


def test_shape_validation():
    grid = SensorConfig().grid()
    with pytest.raises(ValueError):
        SonarFrame(0.0, grid, np.zeros((3, 3, 3), np.float32), np.zeros((0, 4), np.float32))
    with pytest.raises(ValueError):
        SonarFrame(0.0, grid, np.zeros(grid.shape, np.float32), np.zeros((5, 3), np.float32))
