from datetime import date

from health_dashboard.dashboard.render import render_daily_table
from health_dashboard.models import DailyFeature
from health_dashboard.services.relationships import coverage, lagged_correlations, recovery_flags, trailing_average


def feature(day: int, **values) -> DailyFeature:
    return DailyFeature(date=date(2026, 5, day), timezone="Australia/Sydney", source_flags={}, **values)


def test_trailing_average_uses_latest_seven_present_values() -> None:
    rows = [feature(day, hrv=float(day)) for day in range(1, 11)]

    assert trailing_average(rows, "hrv") == 7.0


def test_lagged_correlations_find_next_day_training_recovery_relationship() -> None:
    rows = [
        feature(day, training_load=float(day), hrv=100.0 - float(day - 1))
        for day in range(1, 31)
    ]

    results = lagged_correlations(rows, predictors=["training_load"], outcomes=["hrv"], lags=[1], min_n=14)

    assert results
    assert results[0].lag_days == 1
    assert results[0].r < -0.99
    assert results[0].n == 29


def test_lagged_correlations_support_seven_day_lag() -> None:
    rows = [
        feature(day, training_load=float(day), resting_hr=float(day + 7))
        for day in range(1, 31)
    ]

    results = lagged_correlations(rows, predictors=["training_load"], outcomes=["resting_hr"], lags=[7], min_n=14)

    assert results
    assert results[0].lag_days == 7
    assert results[0].r > 0.99
    assert results[0].n == 23


def test_coverage_marks_sparse_metrics() -> None:
    rows = [feature(1, weight=117.0), feature(2), feature(3, weight=116.8)]

    item = coverage(rows, ["weight"])[0]

    assert item.count == 2
    assert item.total == 3
    assert item.latest_value == 116.8


def test_recovery_flags_surface_low_hrv_against_baseline() -> None:
    rows = [feature(day, hrv=60, resting_hr=45, sleep_duration=8, training_load=10) for day in range(1, 7)]
    rows.append(feature(7, hrv=40, resting_hr=45, sleep_duration=8, training_load=10))

    flags = recovery_flags(rows)

    assert any(flag.label == "HRV below baseline" for flag in flags)


def test_daily_table_renders_friendly_source_badges() -> None:
    row = feature(1, hrv=55)
    row.source_flags = {"hrv": ["whoop"], "training_load": ["strava", "whoop"], "active_energy": ["WHOOP|Samuel’s Apple\u00a0Watch"]}

    html = render_daily_table([row], ["hrv", "training_load", "active_energy"])

    assert "WHOOP" in html
    assert "Strava" in html
    assert "Apple Watch" in html
    assert "source_flags" not in html
