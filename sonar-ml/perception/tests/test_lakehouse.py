"""Lakehouse adapters (sonar-ml/databricks, ADR-0014): rows, partitions, training, pyfunc wrapper."""

import io
import json
import os
import tempfile

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

from sonar_perception import SonarFrame, lakehouse as L  # noqa: E402
from sonar_perception.dataset import generate  # noqa: E402
from sonar_perception.features import FEATURE_NAMES  # noqa: E402
from sonar_perception.lakehouse_model import load_feature_forest, predictions_frame  # noqa: E402

N = 4


@pytest.fixture(scope="module")
def frames_pdf():
    fn = L.generate_partitions("t1", seed=3)
    return pd.concat(list(fn(iter([pd.DataFrame({"scene_index": range(N)})]))), ignore_index=True)


def test_schema_columns_parse_nested_types():
    assert L.schema_columns("a INT, b ARRAY<ARRAY<FLOAT>>, c MAP<STRING, INT>, d STRING") == ["a", "b", "c", "d"]


def test_frame_rows_match_schema(frames_pdf):
    assert list(frames_pdf.columns) == L.schema_columns(L.FRAME_SCHEMA)
    assert len(frames_pdf) == N
    assert frames_pdf["frame_id"].tolist() == [f"t1-{i:06d}" for i in range(N)]
    assert json.loads(frames_pdf["sensing_json"][0])["pings"] == 4  # recommended sensing by default


def test_simulate_scene_matches_dataset_generate():
    sensor, _ = L.make_sensing()
    with tempfile.TemporaryDirectory() as d:
        generate(d, 2, seed=5, sensor=sensor)
        ref = SonarFrame.load(f"{d}/scenes/scene_00001.npz")
    got = L.simulate_scene(5, 1)
    assert np.array_equal(ref.points, got.points)
    assert np.array_equal(ref.point_labels, got.point_labels)


def test_row_roundtrip(frames_pdf):
    frame = L.simulate_scene(3, 2)
    back = L.row_to_frame(frames_pdf.iloc[2])
    assert np.allclose(back.points, frame.points)
    assert np.array_equal(back.point_instances, frame.point_instances)
    assert back.grid.shape == frame.grid.shape
    assert back.meta["object_list"] == frame.meta["object_list"]
    assert back.meta["volume_stored"] is False


def test_npz_bytes_to_row():
    frame = L.simulate_scene(3, 0)
    buf = io.BytesIO()
    frame.save(buf)
    row = L.npz_to_row(buf.getvalue(), "/Volumes/x/frames/a.npz")
    assert row["frame_id"] == "/Volumes/x/frames/a.npz" and row["n_points"] == len(frame.points)
    assert set(row) == set(L.schema_columns(L.FRAME_SCHEMA))


def test_cluster_and_object_partitions(frames_pdf):
    cl = pd.concat(list(L.cluster_partitions()(iter([frames_pdf]))), ignore_index=True)
    ob = pd.concat(list(L.object_partitions()(iter([frames_pdf]))), ignore_index=True)
    assert list(cl.columns) == L.schema_columns(L.CLUSTER_SCHEMA)
    assert list(ob.columns) == L.schema_columns(L.OBJECT_SCHEMA)
    assert len(cl) > 0 and all(len(f) == len(FEATURE_NAMES) for f in cl["features"])
    assert set(cl["label_name"].dropna()) <= set(L.CLASS_NAMES)
    assert (ob["name"] == "floor").any()  # ground truth keeps the floor; outcomes drop it


def _train(frames_pdf, bias=None):
    cl = pd.concat(list(L.cluster_partitions()(iter([frames_pdf]))), ignore_index=True)
    X = np.stack(cl["features"].to_numpy())
    return cl, X, L.train_forest(X, cl["label"].astype(int), cl["scene_id"], cl["conditions"],
                                 n_estimators=20, test_frac=0.25, bias=bias)


def test_train_splits_by_scene(frames_pdf):
    cl, _, (model, metrics, test) = _train(frames_pdf)
    assert not set(cl["scene_id"][test]) & set(cl["scene_id"][~test])
    assert 0 <= metrics["accuracy"] <= 1 and metrics["n_test"] == int(test.sum())


def test_detections_and_outcomes(frames_pdf):
    _, _, (model, _, _) = _train(frames_pdf, bias={"person": 2})
    det = pd.concat(list(L.detection_partitions(model)(iter([frames_pdf]))), ignore_index=True)
    out = pd.concat(list(L.outcome_partitions(model)(iter([frames_pdf]))), ignore_index=True)
    assert list(det.columns) == L.schema_columns(L.DETECTION_SCHEMA)
    assert list(out.columns) == L.schema_columns(L.OUTCOME_SCHEMA)
    assert "noise" not in set(det["class_name"])  # noise clusters are not reported as detections
    assert det["model"].iloc[0] == "random_forest_features+bias(person=2)"
    ok = {"correct", "invisible", "merged", "fragmented"}
    assert all(o in ok or o.startswith("wrong:") for o in out["outcome"])
    n_objects = sum(1 for _, r in frames_pdf.iterrows()
                    for o in json.loads(r["meta_json"])["object_list"] if o["name"] != "floor")
    assert len(out) == n_objects  # every non-floor object gets exactly one outcome


def test_pyfunc_predictions_and_bias(frames_pdf):
    _, X, (model, _, _) = _train(frames_pdf)
    feats = pd.DataFrame(X[:6], columns=FEATURE_NAMES)
    plain = predictions_frame(model, feats)
    assert list(plain.columns) == ["class", "confidence"] + [f"p_{c}" for c in L.CLASS_NAMES]
    probs = plain[[f"p_{c}" for c in L.CLASS_NAMES]].to_numpy()
    assert np.allclose(probs.sum(axis=1), 1)
    biased = predictions_frame(L.FeatureForest(model.forest, {"person": 3}), feats)
    assert (biased["p_person"] >= plain["p_person"] - 1e-12).all()


def test_load_feature_forest_from_mlflow_layout(frames_pdf):
    import joblib

    _, _, (model, _, _) = _train(frames_pdf)
    with tempfile.TemporaryDirectory() as d:
        art = os.path.join(d, "model", "artifacts")
        os.makedirs(art)
        joblib.dump(model.forest, os.path.join(art, "forest.joblib"))
        with open(os.path.join(art, "bias.json"), "w") as f:
            json.dump({"person": 2.0}, f)
        loaded = load_feature_forest(d)
    assert loaded.bias == {"person": 2.0}
