"""Matches acoustic median/majority/spread policy without a claimed accuracy score."""
import pytest
from sonar_bridge.range_adapter import Profile,ObservationBuilder
from sonar_bridge.range_processing import Policy,RangeProcessor


def samples(values):
    b=ObservationBuilder(Profile("synthetic-stat"),now_ms=lambda:1735689600000)
    return [b.line(str(v),"meters-line") for v in values]


def test_acoustic_policy_median_misses_and_tape_error():
    processor=RangeProcessor(Policy(reference_m=1))
    for o in samples([1.01,"timeout",0.99,"timeout",1.02]): result=processor.add(o)
    assert result["available"] and result["median_m"]==1.01
    assert result["missing_count"]==2 and result["valid_count"]==3 and result["sample_count"]==5
    assert result["spread_m"]==pytest.approx(0.03) and result["absolute_error_m"]==pytest.approx(0.01)


def test_spread_withholds_noisy_estimate_outlier_policy_is_explicit():
    observations=samples([1,1.01,0.99,1.02,9])
    plain=RangeProcessor(); filtered=RangeProcessor(Policy(outlier_m=0.2))
    for o in observations: a=plain.add(o); b=filtered.add(o)
    assert not a["available"] and a["median_m"] is None
    assert b["available"] and b["outlier_count"]==1 and b["raw_spread_m"]>8


def test_latest_missing_means_unavailable_and_history_is_bounded():
    processor=RangeProcessor()
    observations=samples([1]*20+["timeout"])
    for o in observations: summary=processor.add(o)
    assert summary["sample_count"]==5 and not summary["available"] and summary["median_m"] is None
    assert len(next(iter(processor.windows.values())))==5


def test_sequence_and_timestamp_and_identity_and_session_reset():
    processor=RangeProcessor(); o=samples([1])[0]
    processor.add(o)
    with pytest.raises(ValueError): processor.add(o)
    changed={**o,"sequence":1,"timestamp_basis":"device_monotonic_ms","capture_timestamp":1}
    with pytest.raises(ValueError): processor.add(changed)
    new={**o,"session_id":"synthetic-new"}
    assert processor.add(new)["sample_count"]==1
    with pytest.raises(ValueError): processor.add({**o,"sequence":3})


def test_two_sensor_windows_are_independent_and_inputs_not_mutated():
    processor=RangeProcessor(); o=samples([1])[0]
    processor.add(o); o["sensor_model"]="modified afterwards"
    other={**samples([2])[0],"sensor_id":"synthetic-second"}
    assert processor.add(other)["sample_count"]==1
    assert len(processor.windows)==2 and next(iter(processor.last.values()))["sensor_model"]!="modified afterwards"
