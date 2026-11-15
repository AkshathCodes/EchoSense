import numpy as np
import pytest
from sonar_perception.augmentation import AcquisitionDiversity, diversify, thin_detections
from sonar_perception.config import SensorConfig, SimConfig
from sonar_perception.sim import random_scene
from sonar_perception.sources.synthetic import simulate_frame
from sonar_perception.config import EnvironmentConfig


def test_height_shift_preserves_normals_identity_and_original_geometry():
    scene = random_scene(np.random.default_rng(2), SimConfig(), SensorConfig())
    original = scene.objects[0].surface.points.copy()
    config = AcquisitionDiversity(original_fraction=0, height_m=(1.6, 1.6))
    changed, sensor, keep, details = diversify(scene, SensorConfig(), config, np.random.default_rng(3))
    np.testing.assert_array_equal(scene.objects[0].surface.points, original)
    np.testing.assert_allclose(changed.objects[0].surface.points[:,2], original[:,2] - .3)
    np.testing.assert_array_equal(changed.objects[0].surface.normals, scene.objects[0].surface.normals)
    assert [o.class_id for o in changed.objects] == [o.class_id for o in scene.objects]
    assert sensor.max_range_m <= 6 and 0 < keep <= 1 and details['applied']


def test_original_fraction_preserves_exact_inputs():
    scene = random_scene(np.random.default_rng(2), SimConfig(), SensorConfig())
    sensor = SensorConfig()
    changed, selected, keep, details = diversify(scene, sensor, AcquisitionDiversity(original_fraction=1), np.random.default_rng(4))
    assert changed is scene and selected is sensor and keep == 1 and not details['applied']


def test_detection_thinning_is_deterministic_and_keeps_labels_aligned():
    scene = random_scene(np.random.default_rng(2), SimConfig(), SensorConfig())
    frame = simulate_frame(scene, SensorConfig(), EnvironmentConfig(), SimConfig(), np.random.default_rng(3))
    a = thin_detections(frame, .5, np.random.default_rng(8))
    b = thin_detections(frame, .5, np.random.default_rng(8))
    np.testing.assert_array_equal(a.points, b.points)
    assert len(a.point_labels) == len(a.point_instances) == len(a.points) < len(frame.points)
    assert a.meta['source'] == 'synthetic' and a.volume is frame.volume


@pytest.mark.parametrize('kwargs',[{'original_fraction':2},{'height_m':(-1,1)}, {'keep_probability':(.5,1.1)}, {'pitch_deg':(10,-10)}, {'reflectivity_gain':(float('nan'),1)}])
def test_bad_diversity_bounds_fail(kwargs):
    with pytest.raises(ValueError): AcquisitionDiversity(**kwargs)


def test_opt_in_disabled_diversity_preserves_default_dataset(tmp_path):
    from sonar_perception.dataset import generate, load_clusters
    generate(tmp_path/'default',2,seed=19,save_frames=False)
    generate(tmp_path/'no-op',2,seed=19,save_frames=False,diversity=AcquisitionDiversity(original_fraction=1))
    a,b=load_clusters(tmp_path/'default'),load_clusters(tmp_path/'no-op')
    assert a.keys()==b.keys()
    for key in a: np.testing.assert_array_equal(a[key],b[key])


def test_experiment_refuses_to_replace_mismatched_existing_dataset(tmp_path):
    import json
    from sonar_perception.experiment import prepare
    existing=tmp_path/'baseline-train';existing.mkdir()
    manifest=existing/'manifest.json'
    manifest.write_text(json.dumps({'seed':1,'n_scenes':5}))
    before=manifest.read_bytes()
    with pytest.raises(ValueError,match='configuration disagrees'): prepare(tmp_path)
    assert manifest.read_bytes()==before
