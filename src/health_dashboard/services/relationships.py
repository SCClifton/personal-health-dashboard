from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import sqrt
from statistics import mean

from health_dashboard.models import DailyFeature


METRIC_LABELS = {
    "weight": "Weight",
    "bmi": "BMI",
    "calories": "Calories",
    "protein": "Protein",
    "carbs": "Carbs",
    "fat": "Fat",
    "systolic_bp": "Systolic BP",
    "diastolic_bp": "Diastolic BP",
    "resting_hr": "Resting HR",
    "hrv": "HRV",
    "sleep_duration": "Sleep",
    "sleep_efficiency": "Sleep efficiency",
    "steps": "Steps",
    "active_energy": "Active energy",
    "training_load": "Training load",
    "workout_count": "Workouts",
    "tirzepatide_dose_mg": "Tirzepatide dose",
}


RELATIONSHIP_METRICS = [
    "weight",
    "calories",
    "protein",
    "systolic_bp",
    "diastolic_bp",
    "resting_hr",
    "hrv",
    "sleep_duration",
    "sleep_efficiency",
    "steps",
    "active_energy",
    "training_load",
    "workout_count",
]


@dataclass(frozen=True)
class Coverage:
    metric: str
    count: int
    total: int
    first_date: date | None
    last_date: date | None
    latest_value: float | None

    @property
    def pct(self) -> float:
        return self.count / self.total * 100 if self.total else 0


@dataclass(frozen=True)
class CorrelationResult:
    predictor: str
    outcome: str
    lag_days: int
    r: float
    n: int


@dataclass(frozen=True)
class Baseline:
    metric: str
    latest: float | None
    trailing_7d: float | None
    delta: float | None


@dataclass(frozen=True)
class RecoveryFlag:
    level: str
    label: str
    detail: str


def metric_label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric.replace("_", " ").title())


def metric_value(row: DailyFeature, metric: str) -> float | None:
    value = getattr(row, metric, None)
    return float(value) if value is not None else None


def coverage(rows: list[DailyFeature], metrics: list[str] = RELATIONSHIP_METRICS) -> list[Coverage]:
    output: list[Coverage] = []
    for metric in metrics:
        present = [(row.date, metric_value(row, metric)) for row in rows if metric_value(row, metric) is not None]
        output.append(
            Coverage(
                metric=metric,
                count=len(present),
                total=len(rows),
                first_date=present[0][0] if present else None,
                last_date=present[-1][0] if present else None,
                latest_value=present[-1][1] if present else None,
            )
        )
    return output


def trailing_average(rows: list[DailyFeature], metric: str, *, end_index: int | None = None, window: int = 7) -> float | None:
    if not rows:
        return None
    idx = len(rows) - 1 if end_index is None else end_index
    window_rows = rows[max(0, idx - window + 1) : idx + 1]
    values = [metric_value(row, metric) for row in window_rows if metric_value(row, metric) is not None]
    return mean(values) if values else None


def baselines(rows: list[DailyFeature], metrics: list[str]) -> list[Baseline]:
    if not rows:
        return [Baseline(metric=metric, latest=None, trailing_7d=None, delta=None) for metric in metrics]
    latest = rows[-1]
    output: list[Baseline] = []
    for metric in metrics:
        latest_value = metric_value(latest, metric)
        avg = trailing_average(rows, metric)
        delta = latest_value - avg if latest_value is not None and avg is not None else None
        output.append(Baseline(metric=metric, latest=latest_value, trailing_7d=avg, delta=delta))
    return output


def recovery_flags(rows: list[DailyFeature]) -> list[RecoveryFlag]:
    if not rows:
        return [RecoveryFlag("muted", "No data", "Connect recovery and training sources to populate this panel.")]

    by_metric = {item.metric: item for item in baselines(rows, ["hrv", "resting_hr", "sleep_duration", "training_load"])}
    flags: list[RecoveryFlag] = []

    hrv = by_metric["hrv"]
    if hrv.latest is not None and hrv.trailing_7d is not None and hrv.latest < hrv.trailing_7d * 0.9:
        flags.append(RecoveryFlag("watch", "HRV below baseline", f"Latest {hrv.latest:.1f} vs 7-day {hrv.trailing_7d:.1f}."))

    rhr = by_metric["resting_hr"]
    if rhr.latest is not None and rhr.trailing_7d is not None and rhr.latest > max(rhr.trailing_7d * 1.05, rhr.trailing_7d + 3):
        flags.append(RecoveryFlag("watch", "Resting HR elevated", f"Latest {rhr.latest:.1f} vs 7-day {rhr.trailing_7d:.1f}."))

    sleep = by_metric["sleep_duration"]
    if sleep.latest is not None and sleep.trailing_7d is not None and (sleep.latest < 6.5 or sleep.latest < sleep.trailing_7d * 0.9):
        flags.append(RecoveryFlag("watch", "Sleep below baseline", f"Latest {sleep.latest:.1f}h vs 7-day {sleep.trailing_7d:.1f}h."))

    load = by_metric["training_load"]
    if load.latest is not None and load.trailing_7d is not None and load.latest > max(load.trailing_7d * 1.5, 40):
        flags.append(RecoveryFlag("watch", "Training load spike", f"Latest {load.latest:.1f} vs 7-day {load.trailing_7d:.1f}."))

    if not flags:
        flags.append(RecoveryFlag("ok", "No recovery flags", "Latest HRV, resting HR, sleep, and load are not outside the simple baseline rules."))
    return flags


def lagged_correlations(
    rows: list[DailyFeature],
    *,
    predictors: list[str] | None = None,
    outcomes: list[str] | None = None,
    lags: list[int] | None = None,
    min_n: int = 14,
) -> list[CorrelationResult]:
    predictors = predictors or ["training_load", "workout_count", "active_energy", "sleep_duration", "sleep_efficiency", "calories", "protein", "weight"]
    outcomes = outcomes or ["hrv", "resting_hr", "sleep_duration", "sleep_efficiency", "weight", "training_load"]
    lags = lags or [0, 1, 2]
    results: list[CorrelationResult] = []
    for predictor in predictors:
        for outcome in outcomes:
            if predictor == outcome:
                continue
            for lag in lags:
                pairs = lagged_pairs(rows, predictor, outcome, lag)
                r = pearson([pair[0] for pair in pairs], [pair[1] for pair in pairs])
                if r is not None and len(pairs) >= min_n:
                    results.append(CorrelationResult(predictor=predictor, outcome=outcome, lag_days=lag, r=r, n=len(pairs)))
    return sorted(results, key=lambda item: (abs(item.r), item.n), reverse=True)


def lagged_pairs(rows: list[DailyFeature], predictor: str, outcome: str, lag_days: int) -> list[tuple[float, float]]:
    values_by_date = {row.date: row for row in rows}
    dates = sorted(values_by_date)
    pairs: list[tuple[float, float]] = []
    for index, day in enumerate(dates):
        outcome_index = index + lag_days
        if outcome_index >= len(dates):
            continue
        predictor_value = metric_value(values_by_date[day], predictor)
        outcome_value = metric_value(values_by_date[dates[outcome_index]], outcome)
        if predictor_value is not None and outcome_value is not None:
            pairs.append((predictor_value, outcome_value))
    return pairs


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    x_mean = mean(xs)
    y_mean = mean(ys)
    x_var = sum((value - x_mean) ** 2 for value in xs)
    y_var = sum((value - y_mean) ** 2 for value in ys)
    if x_var == 0 or y_var == 0:
        return None
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / sqrt(x_var * y_var)


def readiness_note(item: Coverage) -> str:
    if item.count == 0:
        return "No data yet"
    if item.count < 14:
        return "Too sparse for relationship analysis"
    if item.count < 45:
        return "Early signal only"
    return "Usable for trend exploration"
