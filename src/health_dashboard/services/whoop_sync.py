from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from health_dashboard.config import Settings
from health_dashboard.connectors.whoop import WhoopConnector, token_expiry
from health_dashboard.models import ConnectorState, OAuthToken
from health_dashboard.services.ingestion import rebuild_daily_features, store_raw_event
from health_dashboard.services.normalization import MetricValue, normalize_metric_value
from health_dashboard.services.time import parse_datetime


WHOOP_COLLECTIONS = {
    "recovery": "/v2/recovery",
    "cycle": "/v2/cycle",
    "sleep": "/v2/activity/sleep",
    "workout": "/v2/activity/workout",
}


def _metric(
    name: str,
    value: float | int | None,
    unit: str | None,
    observed_start: datetime | None,
    observed_end: datetime | None = None,
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
        source="whoop",
    )


def _millis_to_hours(value: float | int | None) -> float | None:
    if value is None:
        return None
    return float(value) / 1000 / 60 / 60


def _sum_millis(values: list[float | int | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    if not present:
        return None
    return sum(present)


def metrics_from_whoop_record(collection: str, payload: dict[str, Any]) -> list[MetricValue]:
    start = parse_datetime(payload.get("start") or payload.get("created_at"))
    end = parse_datetime(payload.get("end"))
    score = payload.get("score") or {}
    metrics: list[MetricValue | None] = []

    if collection == "recovery":
        metrics.extend(
            [
                _metric("resting_hr", score.get("resting_heart_rate"), "bpm", start, end),
                _metric("hrv", score.get("hrv_rmssd_milli"), "ms", start, end),
            ]
        )
    elif collection == "sleep":
        stage_summary = score.get("stage_summary") or {}
        sleep_millis = _sum_millis(
            [
                stage_summary.get("total_light_sleep_time_milli"),
                stage_summary.get("total_slow_wave_sleep_time_milli"),
                stage_summary.get("total_rem_sleep_time_milli"),
            ]
        )
        if sleep_millis is None and stage_summary.get("total_in_bed_time_milli") is not None:
            sleep_millis = (
                float(stage_summary.get("total_in_bed_time_milli") or 0)
                - float(stage_summary.get("total_awake_time_milli") or 0)
                - float(stage_summary.get("total_no_data_time_milli") or 0)
            )
        metrics.extend(
            [
                _metric("sleep_duration", _millis_to_hours(sleep_millis), "h", start, end),
                _metric("sleep_efficiency", score.get("sleep_efficiency_percentage"), "%", start, end),
            ]
        )
    elif collection == "cycle":
        metrics.extend(
            [
                _metric("training_load", score.get("strain"), "strain", start, end),
            ]
        )
    elif collection == "workout":
        metrics.append(_metric("workout_count", 1, "count", start, end))
    elif collection == "body_measurement":
        observed_at = datetime.now(timezone.utc)
        metrics.extend(
            [
                _metric("weight", payload.get("weight_kilogram"), "kg", observed_at),
                _metric("max_heart_rate", payload.get("max_heart_rate"), "bpm", observed_at),
            ]
        )

    return [metric for metric in metrics if metric is not None]


def source_record_id_for_whoop_record(collection: str, payload: dict[str, Any]) -> str | None:
    if collection == "recovery":
        cycle_id = payload.get("cycle_id")
        sleep_id = payload.get("sleep_id")
        if cycle_id or sleep_id:
            return f"recovery:{cycle_id or 'unknown'}:{sleep_id or 'unknown'}"
        return None
    record_id = payload.get("id")
    if record_id is not None:
        return f"{collection}:{record_id}"
    if collection == "body_measurement":
        return None
    return None


def _save_refreshed_token(db: Session, token: OAuthToken, token_payload: dict) -> None:
    token.access_token = token_payload.get("access_token")
    token.refresh_token = token_payload.get("refresh_token")
    token.token_type = token_payload.get("token_type")
    token.scope = token_payload.get("scope")
    token.expires_at = token_expiry(token_payload)
    db.flush()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _valid_access_token(db: Session, connector: WhoopConnector, token: OAuthToken) -> str:
    if not token.access_token:
        raise ValueError("WHOOP is not authorized. Visit /auth/whoop/start first.")
    refresh_at = _aware_utc(token.expires_at) - timedelta(minutes=2) if token.expires_at else None
    if refresh_at and datetime.now(timezone.utc) >= refresh_at:
        if not token.refresh_token:
            raise ValueError("WHOOP access token is expired and no refresh token is stored. Re-authorize with the offline scope.")
        try:
            token_payload = await connector.refresh_access_token(token.refresh_token)
        except httpx.HTTPStatusError as exc:
            raise ValueError(f"WHOOP token refresh failed with HTTP {exc.response.status_code}. Re-authorize WHOOP at /auth/whoop/start with the offline scope.") from exc
        _save_refreshed_token(db, token, token_payload)
    if not token.access_token:
        raise ValueError("WHOOP token refresh did not return an access token.")
    return token.access_token


async def sync_whoop(
    db: Session,
    settings: Settings,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    token = db.get(OAuthToken, "whoop")
    if token is None:
        raise ValueError("WHOOP is not authorized. Visit /auth/whoop/start first.")

    connector = WhoopConnector(settings, token)
    access_token = await _valid_access_token(db, connector, token)
    batch_id = str(uuid4())
    params: dict[str, str | int] = {"limit": 25}
    if start:
        params["start"] = start.isoformat()
    if end:
        params["end"] = end.isoformat()

    imported = 0
    duplicates = 0
    by_collection: dict[str, dict[str, int]] = {}

    for collection, path in WHOOP_COLLECTIONS.items():
        records = await connector.fetch_paginated_collection(access_token, path, params=params)
        collection_imported = 0
        collection_duplicates = 0
        for record in records:
            _, created = store_raw_event(
                db,
                provider="whoop",
                payload=record,
                import_batch_id=batch_id,
                source_record_id=source_record_id_for_whoop_record(collection, record),
                permissions_scope=collection,
                metrics=metrics_from_whoop_record(collection, record),
            )
            collection_imported += int(created)
            collection_duplicates += int(not created)
        imported += collection_imported
        duplicates += collection_duplicates
        by_collection[collection] = {"imported": collection_imported, "duplicates": collection_duplicates}

    body = await connector.fetch_collection(access_token, "/v2/user/measurement/body")
    _, created = store_raw_event(
        db,
        provider="whoop",
        payload=body,
        import_batch_id=batch_id,
        source_record_id=source_record_id_for_whoop_record("body_measurement", body),
        permissions_scope="body_measurement",
        metrics=metrics_from_whoop_record("body_measurement", body),
    )
    imported += int(created)
    duplicates += int(not created)
    by_collection["body_measurement"] = {"imported": int(created), "duplicates": int(not created)}

    rebuild_daily_features(db)
    state = db.get(ConnectorState, "whoop")
    if state is None:
        state = ConnectorState(connector="whoop", status="connected", detail="Official WHOOP OAuth 2.0 API connector.", next_action="Run WHOOP sync to refresh local data.")
        db.add(state)
    state.status = "connected"
    state.last_sync_at = datetime.now(timezone.utc)
    state.last_error = None
    state.next_action = "Run WHOOP sync again to refresh recovery, sleep, cycles, workouts, and body measurements."
    db.flush()

    return {
        "provider": "whoop",
        "imported": imported,
        "duplicates": duplicates,
        "batch_id": batch_id,
        "collections": by_collection,
    }
