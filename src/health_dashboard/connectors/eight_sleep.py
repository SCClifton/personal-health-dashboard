from __future__ import annotations

from health_dashboard.connectors.base import ConnectorInfo, ConnectorStatus


class EightSleepConnector:
    name = "eight_sleep"

    def status(self) -> ConnectorInfo:
        return ConnectorInfo(
            name=self.name,
            status=ConnectorStatus.FALLBACK_ONLY,
            detail="No stable official public Eight Sleep developer API is configured; password scraping is intentionally excluded.",
            next_action="Sync Eight Sleep data through Apple Health / Health Auto Export where available.",
            official_docs_url=None,
        )
