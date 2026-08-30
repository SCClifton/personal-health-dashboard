from datetime import datetime, timezone

from health_dashboard.config import Settings
from health_dashboard.connectors.base import ConnectorStatus
from health_dashboard.connectors.status import all_connector_info, sync_connector_state
from health_dashboard.models import ConnectorState
from health_dashboard.services.ingestion import store_raw_event


def statuses(infos):
    return {info.name: info.status for info in infos}


def test_connector_status_missing_configured_fallback_and_gated(db_session) -> None:
    settings = Settings(
        database_url="sqlite://",
        health_auto_export_shared_secret="secret",
        whoop_client_id="whoop-id",
        whoop_client_secret="whoop-secret",
        strava_client_id=None,
        strava_client_secret=None,
    )
    info_by_name = statuses(all_connector_info(settings, db_session))

    assert info_by_name["apple_health"] == ConnectorStatus.CONFIGURED
    assert info_by_name["whoop"] == ConnectorStatus.CONFIGURED
    assert info_by_name["strava"] == ConnectorStatus.MISSING_CREDENTIALS
    assert info_by_name["oura"] == ConnectorStatus.MISSING_CREDENTIALS
    assert info_by_name["garmin"] == ConnectorStatus.APPROVAL_GATED
    assert info_by_name["hybrd"] == ConnectorStatus.FALLBACK_ONLY
    assert info_by_name["eight_sleep"] == ConnectorStatus.FALLBACK_ONLY


def test_hybrd_status_requires_official_export_or_api(db_session) -> None:
    settings = Settings(database_url="sqlite://")
    infos = {info.name: info for info in all_connector_info(settings, db_session)}

    assert infos["hybrd"].status == ConnectorStatus.FALLBACK_ONLY
    assert "official export or API" in infos["hybrd"].detail
    assert "Do not scrape" in infos["hybrd"].detail


def test_connector_status_includes_latest_landed_raw_event(db_session) -> None:
    settings = Settings(database_url="sqlite://", health_auto_export_shared_secret="secret")
    store_raw_event(
        db_session,
        provider="apple_health",
        payload={"id": "steps-1", "metric_name": "steps", "value": 1000, "unit": "count", "date": "2026-05-03T08:00:00+10:00"},
    )
    db_session.commit()

    infos = {info.name: info for info in all_connector_info(settings, db_session)}

    assert infos["apple_health"].last_sync_at is not None


def test_connector_state_sync_preserves_existing_last_sync_when_info_has_none(db_session) -> None:
    settings = Settings(database_url="sqlite://", health_auto_export_shared_secret="secret")
    existing = ConnectorState(connector="whoop", status="connected", detail="old", next_action="old")
    existing.last_sync_at = datetime(2026, 5, 3, tzinfo=timezone.utc)
    db_session.add(existing)
    db_session.commit()

    infos = all_connector_info(settings, db_session)
    sync_connector_state(db_session, infos)
    db_session.commit()

    state = db_session.get(ConnectorState, "whoop")
    assert state is not None
    assert state.last_sync_at == existing.last_sync_at
