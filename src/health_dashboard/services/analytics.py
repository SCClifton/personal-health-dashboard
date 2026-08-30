from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean

from health_dashboard.models import DailyFeature
from health_dashboard.services.relationships import metric_value, pearson


@dataclass(frozen=True)
class MetricSnapshot:
    metric: str
    latest: float | None
    average_7d: float | None
    average_28d: float | None
    delta_28d: float | None
    latest_date: date | None
    source: str | None
    present_days: int


@dataclass(frozen=True)
class TrendPoint:
    date: date
    value: float | None
    average_7d: float | None
    average_28d: float | None


@dataclass(frozen=True)
class ChangeWindow:
    metric: str
    days: int
    latest: float | None
    previous: float | None
    change: float | None
    sample_count: int


@dataclass(frozen=True)
class RelationshipReadout:
    metric_a: str
    metric_b: str
    lag_days: int
    r: float | None
    n: int
    missingness_pct: float
    readiness: str
    pairs: list[tuple[date, float, float]]


def calculate_bmi(weight_kg: float | None, height_cm: float | None) -> float | None:
    if weight_kg is None or height_cm is None or height_cm <= 0:
        return None
    height_m = height_cm / 100
    return weight_kg / (height_m * height_m)


def value_for_metric(row: DailyFeature, metric: str, height_cm: float | None = None) -> float | None:
    if metric == "bmi":
        return calculate_bmi(metric_value(row, "weight"), height_cm)
    return metric_value(row, metric)


def source_for_metric(row: DailyFeature, metric: str) -> str | None:
    source_flags = row.source_flags or {}
    source_key = "weight" if metric == "bmi" else metric
    sources = source_flags.get(source_key) or []
    if not sources:
        return None
    return str(sources[0])


def rolling_average_at(rows: list[DailyFeature], metric: str, index: int, window: int, height_cm: float | None = None) -> float | None:
    window_rows = rows[max(0, index - window + 1) : index + 1]
    values = [value_for_metric(row, metric, height_cm) for row in window_rows]
    present = [value for value in values if value is not None]
    return mean(present) if present else None


def trend_points(rows: list[DailyFeature], metric: str, height_cm: float | None = None) -> list[TrendPoint]:
    return [
        TrendPoint(
            date=row.date,
            value=value_for_metric(row, metric, height_cm),
            average_7d=rolling_average_at(rows, metric, index, 7, height_cm),
            average_28d=rolling_average_at(rows, metric, index, 28, height_cm),
        )
        for index, row in enumerate(rows)
    ]


def metric_snapshot(rows: list[DailyFeature], metric: str, height_cm: float | None = None) -> MetricSnapshot:
    present = [(row, value_for_metric(row, metric, height_cm)) for row in rows if value_for_metric(row, metric, height_cm) is not None]
    if not present:
        return MetricSnapshot(metric, None, None, None, None, None, None, 0)
    latest_row, latest = present[-1]
    latest_index = rows.index(latest_row)
    average_7d = rolling_average_at(rows, metric, latest_index, 7, height_cm)
    average_28d = rolling_average_at(rows, metric, latest_index, 28, height_cm)
    delta_28d = latest - average_28d if latest is not None and average_28d is not None else None
    return MetricSnapshot(
        metric=metric,
        latest=latest,
        average_7d=average_7d,
        average_28d=average_28d,
        delta_28d=delta_28d,
        latest_date=latest_row.date,
        source=source_for_metric(latest_row, metric),
        present_days=len(present),
    )


def change_window(rows: list[DailyFeature], metric: str, days: int, height_cm: float | None = None) -> ChangeWindow:
    present = [(row.date, value_for_metric(row, metric, height_cm)) for row in rows if value_for_metric(row, metric, height_cm) is not None]
    if not present:
        return ChangeWindow(metric, days, None, None, None, 0)
    latest_date, latest = present[-1]
    target = latest_date - timedelta(days=days)
    earlier = [(day, value) for day, value in present if day <= target]
    if not earlier:
        return ChangeWindow(metric, days, latest, None, None, len(present))
    _, previous = earlier[-1]
    return ChangeWindow(metric, days, latest, previous, latest - previous if latest is not None and previous is not None else None, len(present))


def paired_relationship(
    rows: list[DailyFeature],
    metric_a: str,
    metric_b: str,
    *,
    lag_days: int = 0,
    days: int | None = None,
    height_cm: float | None = None,
) -> RelationshipReadout:
    filtered = rows
    if days and rows:
        cutoff = rows[-1].date - timedelta(days=days)
        filtered = [row for row in rows if row.date >= cutoff]
    by_date = {row.date: row for row in filtered}
    dates = sorted(by_date)
    pairs: list[tuple[date, float, float]] = []
    possible = 0
    for index, day in enumerate(dates):
        other_index = index + lag_days
        if other_index >= len(dates):
            continue
        possible += 1
        a_value = value_for_metric(by_date[day], metric_a, height_cm)
        b_day = dates[other_index]
        b_value = value_for_metric(by_date[b_day], metric_b, height_cm)
        if a_value is not None and b_value is not None:
            pairs.append((day, a_value, b_value))
    r = pearson([item[1] for item in pairs], [item[2] for item in pairs])
    n = len(pairs)
    missingness = 100 - (n / possible * 100) if possible else 100.0
    if n < 14:
        readiness = "data_insufficient"
    elif n < 45:
        readiness = "early_signal"
    else:
        readiness = "usable"
    return RelationshipReadout(metric_a, metric_b, lag_days, r, n, missingness, readiness, pairs)
