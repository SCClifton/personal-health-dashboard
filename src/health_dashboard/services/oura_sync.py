from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from health_dashboard.config import Settings
from health_dashboard.connectors.oura import OuraConnector, oura_token_expiry
from health_dashboard.models import ConnectorState, OAuthToken
from health_dashboard.services.ingestion import rebuild_daily_features, store_raw_event
from health_dashboard.services.normalization import MetricValue, normalize_metric_value
from health_dashboard.services.time import parse_datetime


@dataclass(frozen=True)
class OuraCollection:
    name: str
    params: str
    max_window_days: int | None = None


OURA_COLLECTIONS = [
    OuraCollection("sleep", "date"),
    OuraCollection("daily_sleep", "date"),
    OuraCollection("daily_readiness", "date"),
    OuraCollection("daily_activity", "date"),
    # Oura's heart-rate time series accepts only short datetime ranges. Seven
    # day windows are conservative and make long initial backfills repeatable.
    OuraCollection("heartrate", "datetime", max_window_days=7),
    OuraCollection("daily_spo2", "date"),
    OuraCollection("workout", "date"),
    OuraCollection("daily_stress", "date"),
    OuraCollection("daily_resilience", "date"),
    OuraCollection("daily_cardiovascular_age", "date"),
    OuraCollection("vO2_max", "date"),
    OuraCollection("sleep_time", "date"),
    OuraCollection("ring_configuration", "none"),
    OuraCollection("ring_battery_level", "datetime"),
]


def _metric(
    name: str,
    value: float | int | None,
    unit: str | None,
    observed_start: datetime | None,
    observed_end: datetime | None = None,
    *,
    source: str = "oura",
) -> MetricValue | None:
    if value is None or observed_start is None:
        return None
    metric_name, normalized, out_unit = normalize_metric_value(name, float(value), unit)
    return MetricValue(
        metric_name=metric_name,
        value_numeric=normalized,
        value_text=None,
        unit=out_unit,
        observed_start=observed_start,
        observed_end=observed_end,
        aggregation_window="event",
        confidence=1.0,
        source=source,
    )


def _text_metric(name: str, value: str | None, observed_start: datetime | None) -> MetricValue | None:
    if not value or observed_start is None:
        return None
    return MetricValue(
        metric_name=name,
        value_numeric=None,
        value_text=value,
        unit=None,
        observed_start=observed_start,
        aggregation_window="event",
        confidence=1.0,
        source="oura",
    )


def _observed_day(payload: dict[str, Any]) -> datetime | None:
    return parse_datetime(payload.get("timestamp") or payload.get("day"))


def _numeric(value: Any, *keys: str) -> float | int | None:
    if isinstance(value, dict):
        for key in keys or ("average", "avg", "value"):
            if value.get(key) is not None:
                return value[key]
        return None
    if value is None:
        return None
    return value


def metrics_from_oura_record(collection: str, payload: dict[str, Any]) -> list[MetricValue]:
    metrics: list[MetricValue | None] = []

    if collection == "sleep":
        start = parse_datetime(payload.get("bedtime_start"))
        end = parse_datetime(payload.get("bedtime_end"))
        metrics.extend(
            [
                _metric("hrv", payload.get("average_hrv"), "ms", start, end),
                _metric("sleep_duration", payload.get("total_sleep_duration"), "seconds", start, end),
                _metric("sleep_efficiency", payload.get("efficiency"), "%", start, end),
                _metric("sleep_average_hr", payload.get("average_heart_rate"), "bpm", start, end),
                _metric("sleep_lowest_hr", payload.get("lowest_heart_rate"), "bpm", start, end),
                _metric("respiratory_rate", payload.get("average_breath"), "count/min", start, end),
            ]
        )
    elif collection == "daily_sleep":
        observed = _observed_day(payload)
        metrics.append(_metric("sleep_score", payload.get("score"), "score", observed))
    elif collection == "daily_readiness":
        observed = _observed_day(payload)
        metrics.extend(
            [
                _metric("readiness_score", payload.get("score"), "score", observed),
                _metric("temperature_deviation", payload.get("temperature_deviation"), "degC", observed),
                _metric("temperature_trend_deviation", payload.get("temperature_trend_deviation"), "degC", observed),
            ]
        )
    elif collection == "daily_activity":
        observed = _observed_day(payload)
        metrics.extend(
            [
                _metric("steps", payload.get("steps"), "count", observed),
                _metric("active_energy", payload.get("active_calories"), "kcal", observed),
                _metric("oura_activity_score", payload.get("score"), "score", observed),
            ]
        )
    elif collection == "heartrate":
        observed = parse_datetime(payload.get("timestamp"))
        metrics.append(_metric("heart_rate", payload.get("bpm"), "bpm", observed))
    elif collection == "daily_spo2":
        observed = _observed_day(payload)
        spo2 = _numeric(payload.get("spo2_percentage"), "average", "avg", "value")
        metrics.extend(
            [
                _metric("blood_oxygen_saturation", spo2, "%", observed),
                _metric("breathing_disturbance_index", payload.get("breathing_disturbance_index"), "count", observed),
            ]
        )
    elif collection == "workout":
        start = parse_datetime(payload.get("start_datetime"))
        end = parse_datetime(payload.get("end_datetime"))
        metrics.extend(
            [
                _metric("workout_count", 1, "count", start, end),
                _metric("active_energy", payload.get("calories"), "kcal", start, end),
                _metric("distance", payload.get("distance"), "m", start, end),
            ]
        )
    elif collection == "daily_stress":
        observed = _observed_day(payload)
        metrics.extend(
            [
                _metric("oura_stress_high_duration", payload.get("stress_high"), "seconds", observed),
                _metric("oura_recovery_high_duration", payload.get("recovery_high"), "seconds", observed),
                _text_metric("oura_stress_summary", payload.get("day_summary"), observed),
            ]
        )
    elif collection == "daily_resilience":
        observed = _observed_day(payload)
        metrics.append(_text_metric("oura_resilience_level", payload.get("level"), observed))
    elif collection == "daily_cardiovascular_age":
        observed = _observed_day(payload)
        metrics.extend(
            [
                _metric("vascular_age", payload.get("vascular_age"), "years", observed),
                _metric("pulse_wave_velocity", payload.get("pulse_wave_velocity"), "m/s", observed),
            ]
        )
    elif collection == "vO2_max":
        observed = _observed_day(payload)
        metrics.append(_metric("vo2_max", payload.get("vo2_max"), "ml/(kg*min)", observed))
    elif collection == "sleep_time":
        observed = _observed_day(payload)
        metrics.append(_text_metric("oura_sleep_time_status", payload.get("status"), observed))
    elif collection == "ring_battery_level":
        observed = parse_datetime(payload.get("timestamp"))
        metrics.append(_metric("ring_battery_level", payload.get("level"), "%", observed))

    return [metric for metric in metrics if metric is not None]


def source_record_id_for_oura_record(collection: str, payload: dict[str, Any]) -> str | None:
    record_id = payload.get("id")
    if record_id is not None:
        return f"{collection}:{record_id}"
    for key in ("timestamp", "day", "start_datetime", "bedtime_start"):
        value = payload.get(key)
        if value is not None:
            return f"{collection}:{value}"
    return None


def _save_refreshed_token(db: Session, token: OAuthToken, token_payload: dict) -> None:
    token.access_token = token_payload.get("access_token")
    token.refresh_token = token_payload.get("refresh_token")
    token.token_type = token_payload.get("token_type")
    token.scope = token_payload.get("scope")
    token.expires_at = oura_token_expiry(token_payload)
    db.flush()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _valid_access_token(db: Session, connector: OuraConnector, token: OAuthToken | None, settings: Settings) -> str:
    if token is None:
        if settings.oura_personal_access_token:
            return settings.oura_personal_access_token
        raise ValueError("Oura is not authorized. Visit /auth/oura/start first.")
    if not token.access_token:
        raise ValueError("Oura is not authorized. Visit /auth/oura/start first.")
    refresh_at = _aware_utc(token.expires_at) - timedelta(minutes=5) if token.expires_at else None
    if refresh_at and datetime.now(timezone.utc) >= refresh_at:
        if not token.refresh_token:
            raise ValueError("Oura access token is expired and no refresh token is stored. Re-authorize Oura at /auth/oura/start.")
        try:
            token_payload = await connector.refresh_access_token(token.refresh_token)
        except httpx.HTTPStatusError as exc:
            raise ValueError(f"Oura token refresh failed with HTTP {exc.response.status_code}. Re-authorize Oura at /auth/oura/start.") from exc
        _save_refreshed_token(db, token, token_payload)
    if not token.access_token:
        raise ValueError("Oura token refresh did not return an access token.")
    return token.access_token


def _params_for_collection(collection: OuraCollection, start: datetime | None, end: datetime | None) -> dict[str, str]:
    if collection.params == "none":
        return {}
    if collection.params == "datetime":
        params: dict[str, str] = {}
        if start:
            params["start_datetime"] = _aware_utc(start).isoformat()
        if end:
            params["end_datetime"] = _aware_utc(end).isoformat()
        return params
    params = {}
    if start:
        params["start_date"] = _aware_utc(start).date().isoformat()
    if end:
        params["end_date"] = _aware_utc(end).date().isoformat()
    return params


def _collection_windows(
    collection: OuraCollection,
    start: datetime | None,
    end: datetime | None,
) -> list[tuple[datetime | None, datetime | None]]:
    if not collection.max_window_days or start is None or end is None:
        return [(start, end)]

    current = _aware_utc(start)
    finish = _aware_utc(end)
    if current >= finish:
        return [(current, finish)]

    windows: list[tuple[datetime, datetime]] = []
    window_size = timedelta(days=collection.max_window_days)
    while current < finish:
        window_end = min(current + window_size, finish)
        windows.append((current, window_end))
        current = window_end
    return windows


async def sync_oura(
    db: Session,
    settings: Settings,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    token = db.get(OAuthToken, "oura")
    connector = OuraConnector(settings, token)
    access_token = await _valid_access_token(db, connector, token, settings)
    batch_id = str(uuid4())
    imported = 0
    duplicates = 0
    by_collection: dict[str, dict[str, Any]] = {}
    collection_errors: list[str] = []

    for collection in OURA_COLLECTIONS:
        records: list[dict[str, Any]] = []
        collection_error: str | None = None
        for window_start, window_end in _collection_windows(collection, start, end):
            try:
                records.extend(
                    await connector.fetch_paginated_collection(
                        access_token,
                        collection.name,
                        params=_params_for_collection(collection, window_start, window_end),
                    )
                )
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                # Oura returns 401 as well as 403 for a valid token that lacks
                # access to an individual collection (observed for daily_spo2).
                # Preserve the other authorised collections and report the gap.
                if status_code not in {400, 401, 403, 404}:
                    raise
                collection_error = f"HTTP {status_code}"
                collection_errors.append(f"{collection.name}: {collection_error}")
                break
        collection_imported = 0
        collection_duplicates = 0
        for record in records:
            _, created = store_raw_event(
                db,
                provider="oura",
                payload=record,
                import_batch_id=batch_id,
                source_record_id=source_record_id_for_oura_record(collection.name, record),
                permissions_scope=collection.name,
                metrics=metrics_from_oura_record(collection.name, record),
            )
            collection_imported += int(created)
            collection_duplicates += int(not created)
        imported += collection_imported
        duplicates += collection_duplicates
        collection_result: dict[str, Any] = {"imported": collection_imported, "duplicates": collection_duplicates}
        if collection_error:
            collection_result["error"] = collection_error
        by_collection[collection.name] = collection_result

    rebuild_daily_features(db)
    state = db.get(ConnectorState, "oura")
    if state is None:
        state = ConnectorState(connector="oura", status="connected", detail="Official Oura API v2 connector.", next_action="Run Oura sync to refresh local data.")
        db.add(state)
    state.status = "connected"
    state.last_sync_at = datetime.now(timezone.utc)
    state.last_error = "; ".join(collection_errors) if collection_errors else None
    if collection_errors:
        state.next_action = "Review Oura collection permissions; successful collections remain current and the sync will retry gaps."
    else:
        state.next_action = "Run Oura sync again to refresh sleep, readiness, activity, stress, SpO2, and device context."
    db.flush()

    return {
        "provider": "oura",
        "imported": imported,
        "duplicates": duplicates,
        "batch_id": batch_id,
        "collections": by_collection,
    }
