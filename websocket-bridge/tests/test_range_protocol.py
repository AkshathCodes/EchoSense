"""Synthetic contract fixtures; no hardware measurement claims."""
import copy
import json
import pytest
from sonar_bridge.range_adapter import Profile,ObservationBuilder
from sonar_bridge.range_protocol import REQUIRED,validate,encode,decode,MAX_BYTES


def sample():
    return ObservationBuilder(Profile("synthetic-sensor"),session_id="synthetic-session",now_ms=lambda:1735689600000).line("1.25","meters-line")


def test_roundtrip_preserves_raw_and_no_xyz():
    o=sample(); before=copy.deepcopy(o)
    assert decode(encode(o))==o==before
    assert o["distance_m"]==o["raw_distance"]==1.25 and o["sensor_pose"] is None
    assert "points" not in o and o["source"]=="synthetic"


@pytest.mark.parametrize("field",sorted(REQUIRED))
def test_required_fields(field):
    o=sample(); del o[field]
    with pytest.raises(ValueError): validate(o)


@pytest.mark.parametrize("field,value",[
 ("schema_version",2),("schema_version",True),("sequence",-1),("sequence",1.5),
 ("session_id","../x"),("sensor_model",""),("sensor_modality","lidar_frame"),
 ("distance_m",float("nan")),("distance_m",float("inf")),("distance_m",-1),("distance_m",0),
 ("raw_unit","feet"),("raw_distance",125),("valid",False),("timed_out",True),
 ("source","hardware"),("timestamp_basis","unknown"),("capture_timestamp",12),
 ("capture_timestamp",True),("coordinate_frame","arkit_world"),("sensor_pose",{"position_m":[0,0,0]}),
])
def test_bad_values(field,value):
    o=sample(); o[field]=value
    with pytest.raises(ValueError): validate(o)


@pytest.mark.parametrize("text",['{','[]','{"x":NaN}','{"x":1,"x":2}',' '*(MAX_BYTES+1)])
def test_malformed_json(text):
    with pytest.raises(ValueError): decode(text)


def test_timeout_is_null_and_unit_conversion_explicit():
    b=ObservationBuilder(Profile("synthetic-sensor"),now_ms=lambda:1735689600000)
    timeout=b.line("timeout","meters-line")
    assert timeout["distance_m"] is None and timeout["timed_out"] and not timeout["valid"]
    o=b.line(json.dumps({"distance":1250,"units":"mm","status":"valid","timestamp":200,"timestamp_basis":"device_monotonic_ms","sequence":9}),"structured")
    assert o["distance_m"]==1.25 and o["raw_distance"]==1250 and o["capture_timestamp"]==200 and o["sequence"]==9


def test_verified_pose_requires_measured_frame_and_calibration():
    o=sample(); o.update(calibration_status="pose_verified",coordinate_frame="measured-rig-1",
        sensor_pose={"position_m":[1,2,3],"direction_unit":[0,0,-1],"calibration_id":"tabletop-calibration"})
    assert validate(o)==o
    o["sensor_pose"]["direction_unit"]=[0,0,2]
    with pytest.raises(ValueError): validate(o)
