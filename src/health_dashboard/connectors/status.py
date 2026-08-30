from __future__ import annotations

from dataclasses import replace

from sqlalchemy import func
from sqlalchemy.orm import Session

from health_dashboard.config import Settings
from health_dashboard.connectors.apple_health import AppleHealthConnector
from health_dashboard.connectors.base import ConnectorInfo, ConnectorStatus
from health_dashboard.connectors.eight_sleep import EightSleepConnector
from health_dashboard.connectors.garmin import GarminConnector
from health_dashboard.connectors.hybrd import HybrdConnector
from health_dashboard.connectors.oura import OuraConnector
from health_dashboard.connectors.strava import StravaConnector
from health_dashboard.connectors.whoop import WhoopConnector
from health_dashboard.models import ConnectorState, OAuthToken, RawEvent


def credential_status(required: list[str | None]) -> ConnectorStatus:
    return ConnectorStatus.CONFIGURED if all(required) else ConnectorStatus.MISSING_CREDENTIALS


def all_connector_info(settings: Settings, db: Session) -> list[ConnectorInfo]:
    tokens = {token.provider: token for token in db.query(OAuthToken).all()}
    infos = [
        AppleHealthConnector(settings).status(),
        WhoopConnector(settings, tokens.get("whoop")).status(),
        StravaConnector(settings, tokens.get("strava")).status(),
        OuraConnector(settings, tokens.get("oura")).status(),
        GarminConnector(settings).status(),
        HybrdConnector().status(),
        EightSleepConnector().status(),
        manual_connector("bp", "Blood pressure adapter for Apple Health, Hilo/Aktiia export, CSV, and manual cuff data.", "Enable Hilo Apple Health sync or import a CSV/export. Do not scrape Hilo or Garmin Connect."),
        manual_connector("weight", "Manual/body-scale weight CSV/API adapter", "Import a CSV or add a future Withings adapter."),
        manual_connector("nutrition", "Nutrition CSV/import adapter", "Import MyFitnessPal Premium export zip/CSV or add Cronometer later."),
        manual_connector("medication", "Local tirzepatide dose log", "Use the medication endpoint or dashboard form."),
    ]
    return [with_local_activity(db, info) for info in infos]


def manual_connector(name: str, detail: str, next_action: str) -> ConnectorInfo:
    return ConnectorInfo(name=name, status=ConnectorStatus.CONFIGURED, detail=detail, next_action=next_action)


def sync_connector_state(db: Session, infos: list[ConnectorInfo]) -> None:
    for info in infos:
        state = db.get(ConnectorState, info.name)
        if state is None:
            state = ConnectorState(connector=info.name, status=info.status.value, detail=info.detail, next_action=info.next_action)
            db.add(state)
        state.status = info.status.value
        state.detail = info.detail
        state.next_action = info.next_action
        if info.last_sync_at is not None:
            state.last_sync_at = info.last_sync_at
        state.last_error = info.last_error
    db.flush()


def with_local_activity(db: Session, info: ConnectorInfo) -> ConnectorInfo:
    state = db.get(ConnectorState, info.name)
    latest_raw = db.query(func.max(RawEvent.received_at)).filter(RawEvent.provider == info.name).scalar()
    last_sync_at = info.last_sync_at
    if state and state.last_sync_at and (last_sync_at is None or state.last_sync_at > last_sync_at):
        last_sync_at = state.last_sync_at
    if latest_raw and (last_sync_at is None or latest_raw > last_sync_at):
        last_sync_at = latest_raw
    return replace(info, last_sync_at=last_sync_at, last_error=info.last_error or (state.last_error if state else None))
