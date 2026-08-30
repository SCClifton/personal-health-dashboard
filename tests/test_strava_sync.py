from datetime import date
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from health_dashboard.models import OAuthToken
from health_dashboard.models import DailyFeature
from health_dashboard.services.ingestion import rebuild_daily_features, store_raw_event
from health_dashboard.services.strava_sync import (
    _valid_access_token,
    is_strava_run,
    metrics_from_strava_activity,
    source_record_id_for_strava_activity,
    source_record_id_for_strava_activity_detail,
    source_record_id_for_strava_activity_laps,
    source_record_id_for_strava_activity_streams,
)


def test_strava_activity_metrics_include_workout_energy_and_load() -> None:
    payload = {
        "id": 123,
        "start_date": "2026-05-03T07:00:00Z",
        "elapsed_time": 3600,
        "distance": 10_000,
        "kilojoules": 1200,
        "suffer_score": 73,
    }

    metrics = metrics_from_strava_activity(payload)

    by_name = {metric.metric_name: metric for metric in metrics}
    assert by_name["workout_count"].value_numeric == 1
    assert by_name["active_energy"].value_numeric == 1200 / 4.184
    assert by_name["active_energy"].unit == "kcal"
    assert by_name["training_load"].value_numeric == 73
    assert by_name["distance"].value_numeric == 10
    assert by_name["distance"].unit == "km"


def test_strava_records_are_deduped_by_activity_source_id(db_session) -> None:
    payload = {
        "id": 123,
        "start_date": "2026-05-03T07:00:00Z",
        "elapsed_time": 3600,
    }
    source_record_id = source_record_id_for_strava_activity(payload)

    first, created_first = store_raw_event(db_session, provider="strava", payload=payload, source_record_id=source_record_id, metrics=metrics_from_strava_activity(payload))
    second, created_second = store_raw_event(db_session, provider="strava", payload=payload, source_record_id=source_record_id, metrics=metrics_from_strava_activity(payload))
    db_session.commit()

    assert first.id == second.id
    assert source_record_id == "activity:123"
    assert created_first is True
    assert created_second is False


def test_strava_detail_lap_and_stream_source_ids_are_stable() -> None:
    assert source_record_id_for_strava_activity_detail(123) == "activity:123:detail"
    assert source_record_id_for_strava_activity_laps(123) == "activity:123:laps"
    assert source_record_id_for_strava_activity_streams(123) == "activity:123:streams"


def test_strava_run_detection_accepts_run_sport_types() -> None:
    assert is_strava_run({"sport_type": "Run"}) is True
    assert is_strava_run({"sport_type": "TrailRun"}) is True
    assert is_strava_run({"type": "Ride"}) is False


@pytest.mark.asyncio
async def test_expired_strava_refresh_failure_requests_reauthorization(db_session) -> None:
    token = OAuthToken(
        provider="strava",
        access_token="expired",
        refresh_token="bad-refresh",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(token)
    db_session.commit()

    class FailingConnector:
        async def refresh_access_token(self, refresh_token):
            request = httpx.Request("POST", "https://www.strava.com/oauth/token")
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

    with pytest.raises(ValueError, match="/auth/strava/start"):
        await _valid_access_token(db_session, FailingConnector(), token)


def test_strava_workout_count_beats_apple_health_workout_count(db_session) -> None:
    apple_payload = {
        "id": "apple-workout",
        "metric_name": "workout_count",
        "value": 1,
        "unit": "count",
        "date": "2026-05-03T08:00:00+10:00",
        "source": "apple_health",
    }
    strava_payload = {
        "id": 123,
        "start_date": "2026-05-03T07:00:00Z",
        "elapsed_time": 3600,
    }

    store_raw_event(db_session, provider="apple_health", payload=apple_payload)
    store_raw_event(
        db_session,
        provider="strava",
        payload=strava_payload,
        source_record_id=source_record_id_for_strava_activity(strava_payload),
        metrics=metrics_from_strava_activity(strava_payload),
    )
    rebuild_daily_features(db_session, tz_name="Australia/Sydney")
    db_session.commit()

    feature = db_session.get(DailyFeature, {"date": date(2026, 5, 3), "timezone": "Australia/Sydney"})
    assert feature is not None
    assert feature.workout_count == 1
    assert feature.source_flags["workout_count"] == ["strava"]
