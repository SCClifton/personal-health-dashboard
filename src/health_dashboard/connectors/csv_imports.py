from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from health_dashboard.config import get_settings
from health_dashboard.services.normalization import MetricValue, metric_from_payload


def parse_csv_metrics(content: bytes, provider: str, source: str) -> list[tuple[dict, list[MetricValue]]]:
    rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    parsed: list[tuple[dict, list[MetricValue]]] = []
    for index, row in enumerate(rows):
        payload = {k.strip(): v for k, v in row.items() if k is not None}
        payload.setdefault("id", stable_csv_row_id(payload, source=source, index=index))
        metrics = row_to_metrics(payload, provider=provider, source=source)
        parsed.append((payload, metrics))
    return parsed


def parse_zip_metrics(content: bytes, provider: str, source: str) -> list[tuple[dict, list[MetricValue]]]:
    parsed: list[tuple[dict, list[MetricValue]]] = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            if name.lower().endswith(".csv"):
                parsed.extend(parse_csv_metrics(archive.read(name), provider=provider, source=f"{source}:{name}"))
    return parsed


def row_to_metrics(row: dict, provider: str, source: str) -> list[MetricValue]:
    candidates = []
    lower = {str(k).strip().lower(): v for k, v in row.items()}
    normalized = {normalize_header(k): v for k, v in row.items() if k is not None}
    observed_local = first_value(lower, "observed_at_local") or first_value(normalized, "observedatlocal")
    date_value = with_local_timezone(observed_local) if observed_local else (
        first_value(lower, "observed_at", "timestamp", "start_time", "start date", "date", "day")
        or first_value(normalized, "observedat", "timestamp", "starttime", "startdate", "date", "day")
    )
    for headers, metric, unit in [
        (("weight", "weightkg", "bodyweight"), "weight", None),
        (("weightlbs", "weightlb"), "weight", "lb"),
        (("calories", "calorieskcal", "energykcal"), "calories", "kcal"),
        (("protein", "proteing"), "protein", "g"),
        (("carbs", "carbohydrates", "carbohydratesg", "carbsg"), "carbs", "g"),
        (("fat", "totalfat", "fatg", "totalfatg"), "fat", "g"),
        (("systolic", "systolicbp", "bloodpressuresystolic"), "systolic_bp", "mmHg"),
        (("diastolic", "diastolicbp", "bloodpressurediastolic"), "diastolic_bp", "mmHg"),
        (("exercisecalories", "exercisecalorieskcal"), "active_energy", "kcal"),
        (("steps", "stepcount"), "steps", "count"),
        (("distance", "distancekm"), "distance", "km"),
        (("distancemi", "distancemiles"), "distance", "mi"),
    ]:
        value = first_value(normalized, *headers)
        if value not in (None, "") and date_value:
            payload = {
                "metric_name": metric,
                "value": value,
                "unit": unit or lower.get("unit"),
                "date": date_value,
                "source": source,
                "aggregation_window": "event",
            }
            metric_value = metric_from_payload(provider, payload, default_source=source)
            if metric_value:
                candidates.append(metric_value)
    workout_value = first_value(normalized, "exercise", "activity", "workout", "exercisename")
    if workout_value and date_value:
        payload = {"metric_name": "workout_count", "value": 1, "unit": "count", "date": date_value, "source": source, "aggregation_window": "event"}
        metric_value = metric_from_payload(provider, payload, default_source=source)
        if metric_value:
            candidates.append(metric_value)
    return candidates


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def stable_csv_row_id(row: dict, *, source: str, index: int) -> str:
    normalized = {normalize_header(k): str(v).strip() for k, v in row.items() if k is not None}
    observed = first_value(normalized, "observedatlocal", "observedat", "timestamp", "starttime", "startdate", "date", "day")
    systolic = first_value(normalized, "systolic", "systolicbp", "bloodpressuresystolic")
    diastolic = first_value(normalized, "diastolic", "diastolicbp", "bloodpressurediastolic")
    if observed and (systolic or diastolic):
        heart_rate = first_value(normalized, "heartrate", "hr", "pulse")
        return f"{source}:bp:{observed}:{systolic or ''}:{diastolic or ''}:{heart_rate or ''}"
    return f"{source}:row:{index}:{normalized}"


def with_local_timezone(value: str) -> str:
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(get_settings().local_timezone))
    return parsed.astimezone(timezone.utc).isoformat()


def first_value(row: dict, *keys: str):
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None
