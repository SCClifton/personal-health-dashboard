from datetime import date

from health_dashboard.models import DailyFeature
from health_dashboard.services.analytics import calculate_bmi, metric_snapshot, paired_relationship, trend_points


def feature(day: int, **values) -> DailyFeature:
    return DailyFeature(date=date(2026, 5, day), timezone="Australia/Sydney", source_flags={}, **values)


def test_bmi_calculation_requires_height() -> None:
    assert calculate_bmi(100.0, 200.0) == 25.0
    assert calculate_bmi(100.0, None) is None
    assert calculate_bmi(None, 200.0) is None


def test_bmi_snapshot_uses_weight_and_configured_height() -> None:
    rows = [feature(1, weight=100.0), feature(2, weight=99.0)]

    snapshot = metric_snapshot(rows, "bmi", height_cm=200.0)

    assert snapshot.latest == 24.75
    assert snapshot.present_days == 2


def test_rolling_trends_return_raw_7d_and_28d_values() -> None:
    rows = [feature(day, weight=float(day)) for day in range(1, 30)]

    latest = trend_points(rows, "weight")[-1]

    assert latest.value == 29.0
    assert latest.average_7d == 26.0
    assert latest.average_28d == 15.5


def test_relationship_readiness_gates_small_samples() -> None:
    sparse = [feature(day, training_load=float(day), hrv=100.0 - day) for day in range(1, 10)]
    early = [feature(day, training_load=float(day), hrv=100.0 - day) for day in range(1, 20)]

    sparse_readout = paired_relationship(sparse, "training_load", "hrv")
    early_readout = paired_relationship(early, "training_load", "hrv")

    assert sparse_readout.n == 9
    assert sparse_readout.readiness == "data_insufficient"
    assert early_readout.n == 19
    assert early_readout.readiness == "early_signal"
