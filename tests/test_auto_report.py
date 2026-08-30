import json
from datetime import date, datetime, timezone

import pytest

from health_dashboard.config import Settings
from health_dashboard.models import OAuthToken
from health_dashboard.services.auto_report import build_auto_health_report, provider_auth_detail, render_auto_health_report_markdown
from health_dashboard.services.ingestion import store_raw_event


@pytest.mark.asyncio
async def test_auto_report_flags_stale_latest_daily_row(db_session) -> None:
    store_raw_event(
        db_session,
        provider="whoop",
        payload={
            "id": "hrv-1",
            "metric_name": "hrv",
            "value": 40,
            "unit": "ms",
            "date": "2026-06-01T08:00:00+10:00",
            "source": "whoop",
        },
    )
    db_session.commit()

    report = await build_auto_health_report(
        db_session,
        Settings(database_url="sqlite://", local_timezone="Australia/Sydney"),
        sync=False,
        report_date=date(2026, 6, 4),
    )

    assert report["latest_daily_date"] == "2026-06-01"
    assert report["days_since_latest_daily"] == 3
    assert any("incomplete" in item for item in report["suggestions"])
    assert any("whoop" in item for item in report["facts"])


@pytest.mark.asyncio
async def test_auto_report_summarizes_fresh_core_and_extra_metrics(db_session) -> None:
    rows = [
        ("apple_health", "steps", 8000, "count", "S Clifton"),
        ("apple_health", "respiratory_rate", 15.5, "breaths/min", "Eight Sleep"),
        ("whoop", "weight", 115.2, "kg", "whoop"),
        ("whoop", "hrv", 42.0, "ms", "whoop"),
        ("nutrition", "calories", 2100, "kcal", "myfitnesspal"),
        ("nutrition", "protein", 180, "g", "myfitnesspal"),
    ]
    for provider, metric_name, value, unit, source in rows:
        store_raw_event(
            db_session,
            provider=provider,
            payload={
                "id": f"{provider}-{metric_name}",
                "metric_name": metric_name,
                "value": value,
                "unit": unit,
                "date": "2026-06-04T08:00:00+10:00",
                "source": source,
            },
        )
    db_session.commit()

    report = await build_auto_health_report(
        db_session,
        Settings(database_url="sqlite://", local_timezone="Australia/Sydney"),
        sync=False,
        report_date=date(2026, 6, 4),
    )

    assert report["latest_daily_date"] == "2026-06-04"
    assert report["core_metrics"]["weight"]["latest"] == 115.2
    assert report["core_metrics"]["protein"]["latest"] == 180
    assert any(item["metric"] == "respiratory_rate" for item in report["extra_metrics"])


@pytest.mark.asyncio
async def test_auto_report_sync_skips_missing_provider_tokens(db_session) -> None:
    report = await build_auto_health_report(
        db_session,
        Settings(database_url="sqlite://", local_timezone="Australia/Sydney"),
        sync=True,
        report_date=date(2026, 6, 4),
    )

    by_provider = {item["provider"]: item for item in report["sync_results"]}
    assert by_provider["whoop"]["status"] == "skipped"
    assert by_provider["strava"]["status"] == "skipped"
    assert by_provider["oura"]["status"] == "skipped"
    assert by_provider["apple_health"]["status"] == "checked"


def test_auto_report_explains_oura_app_credentials_without_authorization(db_session) -> None:
    detail = provider_auth_detail(
        db_session,
        Settings(
            database_url="sqlite://",
            local_timezone="Australia/Sydney",
            oura_client_id="client-id",
            oura_client_secret="client-secret",
        ),
        "oura",
    )

    assert detail["can_sync"] is False
    assert "app credentials are loaded" in detail["detail"]
    assert "/auth/oura/start" in detail["detail"]


@pytest.mark.asyncio
async def test_auto_report_sync_allows_oura_personal_access_token_without_oauth_row(db_session, monkeypatch) -> None:
    async def fake_oura(db, settings, *, start=None, end=None):
        assert settings.oura_personal_access_token == "oura-pat"
        return {"provider": "oura", "imported": 4, "duplicates": 1, "collections": {"sleep": {}, "daily_activity": {}}}

    monkeypatch.setattr("health_dashboard.services.auto_report.sync_oura", fake_oura)

    report = await build_auto_health_report(
        db_session,
        Settings(database_url="sqlite://", local_timezone="Australia/Sydney", oura_personal_access_token="oura-pat"),
        sync=True,
        report_date=date(2026, 6, 4),
    )

    by_provider = {item["provider"]: item for item in report["sync_results"]}
    assert by_provider["oura"]["status"] == "synced"
    assert by_provider["oura"]["imported"] == 4


@pytest.mark.asyncio
async def test_auto_report_sync_uses_mocked_connected_provider_functions(db_session, monkeypatch) -> None:
    db_session.add(OAuthToken(provider="whoop", access_token="whoop-token", refresh_token="whoop-refresh"))
    db_session.add(OAuthToken(provider="strava", access_token="strava-token", refresh_token="strava-refresh"))
    db_session.commit()

    async def fake_whoop(db, settings, *, start=None, end=None):
        return {"provider": "whoop", "imported": 2, "duplicates": 3, "collections": {"sleep": {}, "recovery": {}}}

    async def fake_strava(db, settings, *, start=None, end=None):
        return {"provider": "strava", "imported": 1, "duplicates": 0, "activities": 1}

    monkeypatch.setattr("health_dashboard.services.auto_report.sync_whoop", fake_whoop)
    monkeypatch.setattr("health_dashboard.services.auto_report.sync_strava", fake_strava)

    report = await build_auto_health_report(
        db_session,
        Settings(database_url="sqlite://", local_timezone="Australia/Sydney"),
        sync=True,
        report_date=date(2026, 6, 4),
    )

    by_provider = {item["provider"]: item for item in report["sync_results"]}
    assert by_provider["whoop"]["status"] == "synced"
    assert by_provider["whoop"]["imported"] == 2
    assert by_provider["strava"]["status"] == "synced"
    assert by_provider["strava"]["detail"] == "1 activities returned."


@pytest.mark.asyncio
async def test_auto_report_excludes_raw_payloads_tokens_and_hashes(db_session) -> None:
    db_session.add(
        OAuthToken(
            provider="whoop",
            access_token="secret-access-token",
            refresh_token="secret-refresh-token",
            expires_at=datetime(2026, 6, 5, tzinfo=timezone.utc),
        )
    )
    store_raw_event(
        db_session,
        provider="whoop",
        payload={
            "id": "private-row",
            "metric_name": "hrv",
            "value": 44,
            "unit": "ms",
            "date": "2026-06-04T08:00:00+10:00",
            "source": "whoop",
            "private_payload_value": "do-not-leak",
        },
    )
    db_session.commit()

    report = await build_auto_health_report(
        db_session,
        Settings(database_url="sqlite://", local_timezone="Australia/Sydney"),
        sync=False,
        report_date=date(2026, 6, 4),
    )
    rendered = render_auto_health_report_markdown(report)
    serialized = json.dumps(report, sort_keys=True) + rendered

    assert "secret-access-token" not in serialized
    assert "secret-refresh-token" not in serialized
    assert "do-not-leak" not in serialized
    assert "payload_hash" not in serialized
    assert "raw_events" not in serialized
