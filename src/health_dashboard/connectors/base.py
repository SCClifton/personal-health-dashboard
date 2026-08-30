from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class ConnectorStatus(StrEnum):
    CONNECTED = "connected"
    CONFIGURED = "configured"
    MISSING_CREDENTIALS = "missing_credentials"
    APPROVAL_GATED = "approval_gated"
    FALLBACK_ONLY = "fallback_only"
    ERROR = "error"


@dataclass(frozen=True)
class ConnectorInfo:
    name: str
    status: ConnectorStatus
    detail: str
    next_action: str
    official_docs_url: str | None = None
    last_sync_at: datetime | None = None
    last_error: str | None = None


class Connector(Protocol):
    name: str

    def status(self) -> ConnectorInfo:
        ...
