from __future__ import annotations

from health_dashboard.config import Settings
from health_dashboard.connectors.base import ConnectorInfo, ConnectorStatus


class GarminConnector:
    name = "garmin"
    docs_url = "https://developer.garmin.com/gc-developer-program/health-api/"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def status(self) -> ConnectorInfo:
        return ConnectorInfo(
            name=self.name,
            status=ConnectorStatus.APPROVAL_GATED,
            detail="Official Garmin Health API exists, but access requires Garmin Connect Developer Program approval.",
            next_action="Apply for approval; until then use Apple Health, Strava, or file imports as fallback.",
            official_docs_url=self.docs_url,
        )
