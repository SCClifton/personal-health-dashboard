from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from health_dashboard.config import Settings
from health_dashboard.connectors.strava import STRAVA_RUN_STREAM_KEYS, StravaConnector, strava_token_expiry
from health_dashboard.models import ConnectorState, OAuthToken
from health_dashboard.services.ingestion import rebuild_daily_features, store_raw_event
from health_dashboard.services.normalization import MetricValue, normalize_metric_value
from health_dashboard.services.time import parse_datetime


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
        source="strava",
    )


def metrics_from_strava_activity(payload: dict[str, Any]) -> list[MetricValue]:
    start = parse_datetime(payload.get("start_date") or payload.get("start_date_local"))
    end = None
    elapsed_time = payload.get("elapsed_time")
    if start and elapsed_time is not None:
        end = start + timedelta(seconds=float(elapsed_time))

    active_energy = payload.get("kilojoules")
    active_energy_unit = "kilojoule"
    if active_energy is None:
        active_energy = payload.get("calories")
        active_energy_unit = "kcal"

    training_load = payload.get("suffer_score") or payload.get("relative_effort")

    metrics = [
        _metric("workout_count", 1, "count", start, end),
        _metric("distance", payload.get("distance"), "m", start, end),
        _metric("active_energy", active_energy, active_energy_unit, start, end),
        _metric("training_load", training_load, "relative_effort", start, end),
    ]
    return [metric for metric in metrics if metric is not None]


def source_record_id_for_strava_activity(payload: dict[str, Any]) -> str | None:
    activity_id = payload.get("id")
    if activity_id is None:
        return None
    return f"activity:{activity_id}"


def source_record_id_for_strava_activity_part(activity_id: int | str, part: str) -> str:
    return f"activity:{activity_id}:{part}"


def source_record_id_for_strava_activity_detail(activity_id: int | str) -> str:
    return source_record_id_for_strava_activity_part(activity_id, "detail")


def source_record_id_for_strava_activity_laps(activity_id: int | str) -> str:
    return source_record_id_for_strava_activity_part(activity_id, "laps")


def source_record_id_for_strava_activity_streams(activity_id: int | str) -> str:
    return source_record_id_for_strava_activity_part(activity_id, "streams")


def is_strava_run(activity: dict[str, Any]) -> bool:
    sport_type = str(activity.get("sport_type") or activity.get("type") or "").lower()
    return "run" in sport_type


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _save_refreshed_token(db: Session, token: OAuthToken, token_payload: dict) -> None:
    token.access_token = token_payload.get("access_token")
    token.refresh_token = token_payload.get("refresh_token")
    token.token_type = token_payload.get("token_type")
    token.scope = token_payload.get("scope")
    token.expires_at = strava_token_expiry(token_payload)
    db.flush()


async def _valid_access_token(db: Session, connector: StravaConnector, token: OAuthToken) -> str:
    if not token.access_token:
        raise ValueError("Strava is not authorized. Visit /auth/strava/start first.")
    refresh_at = _aware_utc(token.expires_at) - timedelta(minutes=10) if token.expires_at else None
    if refresh_at and datetime.now(timezone.utc) >= refresh_at:
        if not token.refresh_token:
            raise ValueError("Strava access token is expired and no refresh token is stored. Re-authorize Strava.")
        try:
            token_payload = await connector.refresh_access_token(token.refresh_token)
        except httpx.HTTPStatusError as exc:
            raise ValueError(f"Strava token refresh failed with HTTP {exc.response.status_code}. Re-authorize Strava at /auth/strava/start.") from exc
        _save_refreshed_token(db, token, token_payload)
    if not token.access_token:
        raise ValueError("Strava token refresh did not return an access token.")
    return token.access_token


def _unix_timestamp(value: datetime | None) -> int | None:
    if value is None:
        return None
    return int(_aware_utc(value).timestamp())


async def sync_strava(
    db: Session,
    settings: Settings,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    token = db.get(OAuthToken, "strava")
    if token is None:
        raise ValueError("Strava is not authorized. Visit /auth/strava/start first.")

    connector = StravaConnector(settings, token)
    access_token = await _valid_access_token(db, connector, token)
    activities = await connector.fetch_activities(access_token, after=_unix_timestamp(start), before=_unix_timestamp(end))

    batch_id = str(uuid4())
    imported = 0
    duplicates = 0
    for activity in activities:
        _, created = store_raw_event(
            db,
            provider="strava",
            payload=activity,
            import_batch_id=batch_id,
            source_record_id=source_record_id_for_strava_activity(activity),
            permissions_scope="activity",
            metrics=metrics_from_strava_activity(activity),
        )
        imported += int(created)
        duplicates += int(not created)

    rebuild_daily_features(db)
    state = db.get(ConnectorState, "strava")
    if state is None:
        state = ConnectorState(connector="strava", status="connected", detail="Official Strava API connector.", next_action="Run Strava sync to refresh local activities.")
        db.add(state)
    state.status = "connected"
    state.last_sync_at = datetime.now(timezone.utc)
    state.last_error = None
    state.next_action = "Run Strava sync again to refresh activities."
    db.flush()

    return {
        "provider": "strava",
        "imported": imported,
        "duplicates": duplicates,
        "batch_id": batch_id,
        "activities": len(activities),
    }


async def sync_strava_runs(
    db: Session,
    settings: Settings,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    activity_id: int | None = None,
) -> dict[str, Any]:
    token = db.get(OAuthToken, "strava")
    if token is None:
        raise ValueError("Strava is not authorized. Visit /auth/strava/start first.")

    connector = StravaConnector(settings, token)
    access_token = await _valid_access_token(db, connector, token)
    batch_id = str(uuid4())
    imported = 0
    duplicates = 0
    errors: list[str] = []

    if activity_id is not None:
        activities = [{"id": activity_id, "sport_type": "Run"}]
    else:
        fetched = await connector.fetch_activities(access_token, after=_unix_timestamp(start), before=_unix_timestamp(end))
        activities = [activity for activity in fetched if is_strava_run(activity)]

    for activity in activities:
        raw_activity_id = activity.get("id")
        if raw_activity_id is None:
            continue
        try:
            detail = await connector.fetch_activity_detail(access_token, int(raw_activity_id))
            if not is_strava_run(detail):
                continue
            imported_delta, duplicate_delta = _store_strava_activity_summary(db, detail, batch_id)
            imported += imported_delta
            duplicates += duplicate_delta

            _, created = store_raw_event(
                db,
                provider="strava",
                payload=detail,
                import_batch_id=batch_id,
                source_record_id=source_record_id_for_strava_activity_detail(raw_activity_id),
                permissions_scope="activity_detail",
            )
            imported += int(created)
            duplicates += int(not created)

            laps = await connector.fetch_laps(access_token, int(raw_activity_id))
            _, created = store_raw_event(
                db,
                provider="strava",
                payload={"activity_id": raw_activity_id, "start_date": detail.get("start_date"), "laps": laps},
                import_batch_id=batch_id,
                source_record_id=source_record_id_for_strava_activity_laps(raw_activity_id),
                permissions_scope="activity_laps",
            )
            imported += int(created)
            duplicates += int(not created)

            streams = await connector.fetch_streams(access_token, int(raw_activity_id), keys=STRAVA_RUN_STREAM_KEYS)
            _, created = store_raw_event(
                db,
                provider="strava",
                payload={"activity_id": raw_activity_id, "start_date": detail.get("start_date"), "streams": streams},
                import_batch_id=batch_id,
                source_record_id=source_record_id_for_strava_activity_streams(raw_activity_id),
                permissions_scope="activity_streams",
            )
            imported += int(created)
            duplicates += int(not created)
        except httpx.HTTPStatusError as exc:
            errors.append(_strava_activity_error(raw_activity_id, exc))

    rebuild_daily_features(db)
    state = db.get(ConnectorState, "strava")
    if state is None:
        state = ConnectorState(connector="strava", status="connected", detail="Official Strava API connector.", next_action="Run Strava sync to refresh local activities.")
        db.add(state)
    state.status = "connected"
    state.last_sync_at = datetime.now(timezone.utc)
    state.last_error = "; ".join(errors[:3]) if errors else None
    state.next_action = "Run Strava summary sync for daily features or rich run sync for laps and heart-rate streams."
    db.flush()

    return {
        "provider": "strava",
        "imported": imported,
        "duplicates": duplicates,
        "batch_id": batch_id,
        "runs": len(activities),
        "errors": errors,
    }


def _store_strava_activity_summary(db: Session, activity: dict[str, Any], batch_id: str) -> tuple[int, int]:
    _, created = store_raw_event(
        db,
        provider="strava",
        payload=activity,
        import_batch_id=batch_id,
        source_record_id=source_record_id_for_strava_activity(activity),
        permissions_scope="activity",
        metrics=metrics_from_strava_activity(activity),
    )
    return int(created), int(not created)


def _strava_activity_error(activity_id: Any, exc: httpx.HTTPStatusError) -> str:
    status_code = exc.response.status_code
    if status_code in {401, 403}:
        return f"activity {activity_id}: Strava returned {status_code}; re-authorize with activity:read_all if this run is private."
    return f"activity {activity_id}: Strava returned {status_code} while fetching run detail."
