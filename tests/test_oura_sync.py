from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from health_dashboard.config import Settings
from health_dashboard.connectors.oura import OURA_SCOPES, OuraConnector
from health_dashboard.models import DailyFeature, NormalizedMetric, OAuthToken, RawEvent
from health_dashboard.services.ingestion import rebuild_daily_features, store_raw_event
from health_dashboard.services.oura_sync import (
    _valid_access_token,
    metrics_from_oura_record,
    source_record_id_for_oura_record,
    sync_oura,
)
from health_dashboard.services.whoop_sync import metrics_from_whoop_record, source_record_id_for_whoop_record


def test_oura_authorization_url_uses_oauth_scope_contract() -> None:
    settings = Settings(oura_client_id="client-id", oura_client_secret="secret", oura_redirect_uri="http://localhost:8000/auth/oura/callback")

    url = OuraConnector(settings).authorization_url("state-token")
    query = parse_qs(urlparse(url).query)

    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == ["http://localhost:8000/auth/oura/callback"]
    assert set(query["scope"][0].split()) == set(OURA_SCOPES.split())
    assert "spo2Daily" in query["scope"][0].split()
    assert "spo2" not in query["scope"][0].split()


def test_oura_sleep_metrics_are_cautious_and_do_not_map_sleep_hr_to_resting_hr() -> None:
    payload = {
        "id": "sleep-1",
        "bedtime_start": "2026-05-02T22:30:00+10:00",
        "bedtime_end": "2026-05-03T06:30:00+10:00",
        "average_hrv": 42,
        "total_sleep_duration": 25_200,
        "efficiency": 91,
        "average_heart_rate": 54,
        "lowest_heart_rate": 47,
    }

    metrics = metrics_from_oura_record("sleep", payload)

    by_name = {metric.metric_name: metric for metric in metrics}
    assert by_name["hrv"].value_numeric == 42
    assert by_name["sleep_duration"].value_numeric == 7
    assert by_name["sleep_efficiency"].value_numeric == 91
    assert by_name["sleep_average_hr"].value_numeric == 54
    assert by_name["sleep_lowest_hr"].value_numeric == 47
    assert "resting_hr" not in by_name


def test_oura_records_are_deduped_by_collection_prefixed_source_id(db_session) -> None:
    payload = {
        "id": "sleep-1",
        "bedtime_start": "2026-05-02T22:30:00+10:00",
        "bedtime_end": "2026-05-03T06:30:00+10:00",
        "total_sleep_duration": 25_200,
    }
    source_record_id = source_record_id_for_oura_record("sleep", payload)

    first, created_first = store_raw_event(db_session, provider="oura", payload=payload, source_record_id=source_record_id, metrics=metrics_from_oura_record("sleep", payload))
    second, created_second = store_raw_event(db_session, provider="oura", payload=payload, source_record_id=source_record_id, metrics=metrics_from_oura_record("sleep", payload))
    db_session.commit()

    assert first.id == second.id
    assert source_record_id == "sleep:sleep-1"
    assert created_first is True
    assert created_second is False


@pytest.mark.asyncio
async def test_expired_oura_refresh_failure_requests_reauthorization(db_session) -> None:
    token = OAuthToken(
        provider="oura",
        access_token="expired",
        refresh_token="bad-refresh",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(token)
    db_session.commit()

    class FailingConnector:
        async def refresh_access_token(self, refresh_token):
            request = httpx.Request("POST", "https://api.ouraring.com/oauth/token")
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

    with pytest.raises(ValueError, match="/auth/oura/start"):
        await _valid_access_token(db_session, FailingConnector(), token, Settings())


def test_whoop_hrv_beats_oura_until_concordance_changes_priority(db_session) -> None:
    whoop_payload = {
        "cycle_id": "cycle-1",
        "sleep_id": "sleep-1",
        "created_at": "2026-05-03T07:00:00+10:00",
        "score": {"resting_heart_rate": 50, "hrv_rmssd_milli": 39},
    }
    oura_payload = {
        "id": "oura-sleep-1",
        "bedtime_start": "2026-05-02T22:30:00+10:00",
        "bedtime_end": "2026-05-03T06:30:00+10:00",
        "average_hrv": 44,
    }

    store_raw_event(
        db_session,
        provider="oura",
        payload=oura_payload,
        source_record_id=source_record_id_for_oura_record("sleep", oura_payload),
        metrics=metrics_from_oura_record("sleep", oura_payload),
    )
    store_raw_event(
        db_session,
        provider="whoop",
        payload=whoop_payload,
        source_record_id=source_record_id_for_whoop_record("recovery", whoop_payload),
        metrics=metrics_from_whoop_record("recovery", whoop_payload),
    )
    rebuild_daily_features(db_session, tz_name="Australia/Sydney")
    db_session.commit()

    feature = db_session.get(DailyFeature, {"date": date(2026, 5, 3), "timezone": "Australia/Sydney"})
    assert feature is not None
    assert feature.hrv == 39
    assert feature.source_flags["hrv"] == ["whoop"]


@pytest.mark.asyncio
async def test_sync_oura_stores_raw_records_and_normalized_metrics(db_session, monkeypatch) -> None:
    token = OAuthToken(
        provider="oura",
        access_token="valid",
        refresh_token="refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(token)
    db_session.commit()
    calls: list[str] = []

    class FakeOuraConnector:
        def __init__(self, settings, token=None):
            pass

        async def fetch_paginated_collection(self, access_token, collection, params=None):
            calls.append(collection)
            if collection == "sleep":
                return [
                    {
                        "id": "sleep-1",
                        "bedtime_start": "2026-05-02T22:30:00+10:00",
                        "bedtime_end": "2026-05-03T06:30:00+10:00",
                        "average_hrv": 42,
                        "total_sleep_duration": 25_200,
                    }
                ]
            return []

    monkeypatch.setattr("health_dashboard.services.oura_sync.OuraConnector", FakeOuraConnector)

    result = await sync_oura(db_session, Settings(), start=datetime(2026, 5, 1, tzinfo=timezone.utc), end=datetime(2026, 5, 4, tzinfo=timezone.utc))
    db_session.commit()

    assert result["collections"]["sleep"]["imported"] == 1
    assert "daily_activity" in calls
    assert db_session.query(RawEvent).filter(RawEvent.provider == "oura").count() == 1
    assert db_session.query(NormalizedMetric).filter(NormalizedMetric.provider == "oura", NormalizedMetric.metric_name == "sleep_duration").count() == 1
