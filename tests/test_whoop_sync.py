from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from health_dashboard.models import DailyFeature
from health_dashboard.models import OAuthToken
from health_dashboard.services.ingestion import rebuild_daily_features, store_raw_event
from health_dashboard.services.whoop_sync import _valid_access_token, metrics_from_whoop_record, source_record_id_for_whoop_record


def test_whoop_sleep_metrics_include_duration_and_efficiency(db_session) -> None:
    payload = {
        "id": "sleep-1",
        "start": "2026-05-02T22:30:00+10:00",
        "end": "2026-05-03T06:30:00+10:00",
        "score": {
            "stage_summary": {
                "total_light_sleep_time_milli": 12_000_000,
                "total_slow_wave_sleep_time_milli": 6_000_000,
                "total_rem_sleep_time_milli": 7_200_000,
            },
            "sleep_efficiency_percentage": 87.5,
        },
    }

    metrics = metrics_from_whoop_record("sleep", payload)

    by_name = {metric.metric_name: metric for metric in metrics}
    assert by_name["sleep_duration"].value_numeric == 7.0
    assert by_name["sleep_duration"].unit == "h"
    assert by_name["sleep_efficiency"].value_numeric == 87.5
    assert by_name["sleep_efficiency"].source == "whoop"


def test_whoop_records_are_deduped_by_collection_prefixed_source_id(db_session) -> None:
    payload = {
        "id": "sleep-1",
        "start": "2026-05-03T00:00:00+10:00",
        "score": {"stage_summary": {"total_light_sleep_time_milli": 3_600_000}},
    }
    source_record_id = source_record_id_for_whoop_record("sleep", payload)

    first, created_first = store_raw_event(db_session, provider="whoop", payload=payload, source_record_id=source_record_id, metrics=metrics_from_whoop_record("sleep", payload))
    second, created_second = store_raw_event(db_session, provider="whoop", payload=payload, source_record_id=source_record_id, metrics=metrics_from_whoop_record("sleep", payload))
    db_session.commit()

    assert first.id == second.id
    assert source_record_id == "sleep:sleep-1"
    assert created_first is True
    assert created_second is False


def test_whoop_workout_metrics_do_not_duplicate_cycle_load() -> None:
    payload = {
        "id": "workout-1",
        "start": "2026-05-03T07:00:00+10:00",
        "end": "2026-05-03T08:00:00+10:00",
        "score": {"strain": 8.2, "kilojoule": 1200},
    }

    metrics = metrics_from_whoop_record("workout", payload)

    assert [metric.metric_name for metric in metrics] == ["workout_count"]
    assert metrics[0].value_numeric == 1


def test_whoop_cycle_kilojoule_is_not_active_energy() -> None:
    payload = {
        "id": "cycle-1",
        "start": "2026-05-03T07:00:00+10:00",
        "end": "2026-05-04T07:00:00+10:00",
        "score": {"strain": 8.2, "kilojoule": 10_000},
    }

    metrics = metrics_from_whoop_record("cycle", payload)

    assert [metric.metric_name for metric in metrics] == ["training_load"]
    assert metrics[0].value_numeric == 8.2


@pytest.mark.asyncio
async def test_expired_whoop_refresh_failure_requests_reauthorization(db_session) -> None:
    token = OAuthToken(
        provider="whoop",
        access_token="expired",
        refresh_token="bad-refresh",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(token)
    db_session.commit()

    class FailingConnector:
        async def refresh_access_token(self, refresh_token):
            request = httpx.Request("POST", "https://api.prod.whoop.com/oauth/oauth2/token")
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

    with pytest.raises(ValueError, match="/auth/whoop/start"):
        await _valid_access_token(db_session, FailingConnector(), token)


def test_whoop_sleep_beats_apple_health_sleep_summary(db_session) -> None:
    apple_payload = {
        "id": "apple-sleep",
        "metric_name": "sleep_duration",
        "value": 6.5,
        "unit": "h",
        "date": "2026-05-03T08:00:00+10:00",
        "source": "apple_health",
    }
    whoop_payload = {
        "id": "sleep-1",
        "start": "2026-05-03T00:00:00+10:00",
        "end": "2026-05-03T07:30:00+10:00",
        "score": {"stage_summary": {"total_light_sleep_time_milli": 25_200_000}},
    }

    store_raw_event(db_session, provider="apple_health", payload=apple_payload)
    store_raw_event(
        db_session,
        provider="whoop",
        payload=whoop_payload,
        source_record_id=source_record_id_for_whoop_record("sleep", whoop_payload),
        metrics=metrics_from_whoop_record("sleep", whoop_payload),
    )
    rebuild_daily_features(db_session, tz_name="Australia/Sydney")
    db_session.commit()

    feature = db_session.get(DailyFeature, {"date": date(2026, 5, 3), "timezone": "Australia/Sydney"})
    assert feature is not None
    assert feature.sleep_duration == 7.0
    assert feature.source_flags["sleep_duration"] == ["whoop"]
