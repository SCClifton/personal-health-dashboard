import pytest

from health_dashboard.services.normalization import normalize_metric_value


def test_unit_normalization() -> None:
    metric, value, unit = normalize_metric_value("weight", 220, "lb")
    assert metric == "weight"
    assert value == pytest.approx(99.7903214)
    assert unit == "kg"
    assert normalize_metric_value("calories", 4184, "kJ") == ("calories", 1000.0, "kcal")
    assert normalize_metric_value("protein", 5000, "mg") == ("protein", 5.0, "g")
    assert normalize_metric_value("resting_hr", 62, "count/min") == ("resting_hr", 62, "bpm")
    assert normalize_metric_value("hrv", 41, "ms") == ("hrv", 41, "ms")
    assert normalize_metric_value("systolic_bp", 120, "mmHg") == ("systolic_bp", 120, "mmHg")
    assert normalize_metric_value("distance", 10, "mi") == ("distance", 16.09344, "km")


def test_blood_pressure_aliases_normalize_to_canonical_metrics() -> None:
    assert normalize_metric_value("HKQuantityTypeIdentifierBloodPressureSystolic", 122, "mmHg") == ("systolic_bp", 122, "mmHg")
    assert normalize_metric_value("blood pressure systolic", 122, "mmHg") == ("systolic_bp", 122, "mmHg")
    assert normalize_metric_value("bp_diastolic", 78, "mmHg") == ("diastolic_bp", 78, "mmHg")
