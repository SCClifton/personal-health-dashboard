from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from health_dashboard.services.time import parse_datetime
from health_dashboard.services.units import (
    normalize_distance,
    normalize_duration_hours,
    normalize_energy,
    normalize_grams,
    normalize_passthrough,
    normalize_weight,
)


METRIC_ALIASES = {
    "HKQuantityTypeIdentifierBodyMass": "weight",
    "body_mass": "weight",
    "weight_body_mass": "weight",
    "weight": "weight",
    "calories": "calories",
    "energy": "calories",
    "active_energy": "active_energy",
    "active_energy_burned": "active_energy",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "active_energy",
    "protein": "protein",
    "carbohydrates": "carbs",
    "carbs": "carbs",
    "fat": "fat",
    "systolic": "systolic_bp",
    "systolic_bp": "systolic_bp",
    "bp_systolic": "systolic_bp",
    "bloodpressure_systolic": "systolic_bp",
    "blood_pressure_systolic": "systolic_bp",
    "blood pressure systolic": "systolic_bp",
    "blood_pressure_systolic_mmHg": "systolic_bp",
    "HKQuantityTypeIdentifierBloodPressureSystolic": "systolic_bp",
    "hkquantitytypeidentifierbloodpressuresystolic": "systolic_bp",
    "diastolic": "diastolic_bp",
    "diastolic_bp": "diastolic_bp",
    "bp_diastolic": "diastolic_bp",
    "bloodpressure_diastolic": "diastolic_bp",
    "blood_pressure_diastolic": "diastolic_bp",
    "blood pressure diastolic": "diastolic_bp",
    "blood_pressure_diastolic_mmHg": "diastolic_bp",
    "HKQuantityTypeIdentifierBloodPressureDiastolic": "diastolic_bp",
    "hkquantitytypeidentifierbloodpressurediastolic": "diastolic_bp",
    "resting_hr": "resting_hr",
    "resting_heart_rate": "resting_hr",
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_hr",
    "hrv": "hrv",
    "hrv_rmssd": "hrv",
    "heart_rate_variability": "hrv",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv",
    "sleep_duration": "sleep_duration",
    "sleep_analysis": "sleep_duration",
    "sleep_efficiency": "sleep_efficiency",
    "steps": "steps",
    "step_count": "steps",
    "HKQuantityTypeIdentifierStepCount": "steps",
    "training_load": "training_load",
    "workout_count": "workout_count",
    "distance": "distance",
    "tirzepatide_dose_mg": "tirzepatide_dose_mg",
    "dietary_energy": "calories",
    "total_fat": "fat",
    "walking_running_distance": "distance",
    "walking_+_running_distance": "distance",
}


SOURCE_PRIORITY = {
    "systolic_bp": {"manual_cuff": 100, "omron": 95, "hilo": 85, "aktiia": 85, "apple_health": 30},
    "diastolic_bp": {"manual_cuff": 100, "omron": 95, "hilo": 85, "aktiia": 85, "apple_health": 30},
    "weight": {"withings": 100, "manual": 95, "apple_health": 40, "myfitnesspal": 35},
    "resting_hr": {"whoop": 100, "oura": 95, "garmin": 90, "apple_health": 70},
    "hrv": {"whoop": 100, "oura": 95, "garmin": 90, "eight_sleep": 75, "apple_health": 70},
    "steps": {"garmin": 100, "apple_health": 80, "oura": 75, "myfitnesspal": 35},
    "active_energy": {"garmin": 100, "strava": 95, "apple_health": 80, "oura": 75, "whoop": 70, "myfitnesspal": 35},
    "training_load": {"garmin": 100, "strava": 95, "whoop": 90, "oura": 70, "apple_health": 45},
    "workout_count": {"garmin": 100, "strava": 95, "whoop": 90, "oura": 70, "apple_health": 45, "myfitnesspal": 35},
    "sleep_duration": {"whoop": 100, "oura": 95, "garmin": 90, "eight_sleep": 90, "apple_health": 70},
    "sleep_efficiency": {"whoop": 100, "oura": 95, "garmin": 90, "eight_sleep": 90, "apple_health": 70},
}


@dataclass(frozen=True)
class MetricValue:
    metric_name: str
    value_numeric: float | None
    value_text: str | None
    unit: str | None
    observed_start: datetime
    observed_end: datetime | None = None
    aggregation_window: str | None = None
    confidence: float = 1.0
    source: str | None = None


def canonical_metric_name(name: str) -> str:
    normalized = name.strip()
    return METRIC_ALIASES.get(normalized, METRIC_ALIASES.get(normalized.lower(), normalized))


def normalize_metric_value(name: str, value: float, unit: str | None) -> tuple[str, float, str | None]:
    metric_name = canonical_metric_name(name)
    if metric_name == "weight":
        normalized, out_unit = normalize_weight(value, unit)
    elif metric_name in {"calories", "active_energy"}:
        normalized, out_unit = normalize_energy(value, unit)
    elif metric_name in {"protein", "carbs", "fat"}:
        normalized, out_unit = normalize_grams(value, unit)
    elif metric_name == "distance":
        normalized, out_unit = normalize_distance(value, unit)
    elif metric_name == "sleep_duration":
        normalized, out_unit = normalize_duration_hours(value, unit)
    elif metric_name in {"resting_hr"}:
        normalized, out_unit = normalize_passthrough(value, unit, "bpm")
    elif metric_name == "hrv":
        normalized, out_unit = normalize_passthrough(value, unit, "ms")
    elif metric_name in {"systolic_bp", "diastolic_bp"}:
        normalized, out_unit = normalize_passthrough(value, unit, "mmHg")
    elif metric_name == "tirzepatide_dose_mg":
        normalized, out_unit = normalize_passthrough(value, unit, "mg")
    else:
        normalized, out_unit = value, unit
    return metric_name, normalized, out_unit


def source_priority(metric_name: str, source: str) -> int:
    priority = SOURCE_PRIORITY.get(metric_name, {})
    source_lower = source.lower()
    if source in priority or source_lower in priority:
        return priority.get(source, priority.get(source_lower, 50))
    for key, value in priority.items():
        if key.lower() in source_lower:
            return value
    return 50


def metric_from_payload(provider: str, payload: dict[str, Any], default_source: str | None = None) -> MetricValue | None:
    name = payload.get("metric_name") or payload.get("type") or payload.get("name")
    value = payload.get("value_numeric", payload.get("value"))
    observed_start = parse_datetime(payload.get("observed_start") or payload.get("startDate") or payload.get("date"))
    if not name or value is None or observed_start is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    metric_name, normalized, unit = normalize_metric_value(str(name), numeric, payload.get("unit"))
    return MetricValue(
        metric_name=metric_name,
        value_numeric=normalized,
        value_text=None,
        unit=unit,
        observed_start=observed_start,
        observed_end=parse_datetime(payload.get("observed_end") or payload.get("endDate")),
        aggregation_window=payload.get("aggregation_window"),
        confidence=float(payload.get("confidence", 0.7 if provider == "apple_health" else 1.0)),
        source=payload.get("source") or default_source or provider,
    )
