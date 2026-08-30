from __future__ import annotations

from health_dashboard.connectors.base import ConnectorInfo, ConnectorStatus


class HybrdConnector:
    name = "hybrd"
    docs_url = "https://www.hybrd.com/support"

    def status(self) -> ConnectorInfo:
        return ConnectorInfo(
            name=self.name,
            status=ConnectorStatus.FALLBACK_ONLY,
            detail="HYBRD workout detail intake is blocked until an official export or API sample is available. Do not scrape or reverse engineer the app.",
            next_action="Ask HYBRD support for an official data export/API. Until then, use Strava/Garmin/Apple Health workout summaries as interim training truth.",
            official_docs_url=self.docs_url,
        )
