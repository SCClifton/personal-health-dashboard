from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from health_dashboard.config import Settings
from health_dashboard.connectors.base import ConnectorInfo, ConnectorStatus
from health_dashboard.models import OAuthToken


WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_API_BASE = "https://api.prod.whoop.com/developer"
WHOOP_SCOPES = "offline read:recovery read:cycles read:workout read:sleep read:profile read:body_measurement"


class WhoopConnector:
    name = "whoop"
    docs_url = "https://developer.whoop.com/docs/developing/oauth/"

    def __init__(self, settings: Settings, token: OAuthToken | None = None) -> None:
        self.settings = settings
        self.token = token

    def status(self) -> ConnectorInfo:
        if self.token and self.token.access_token:
            status = ConnectorStatus.CONNECTED
            next_action = "Run a WHOOP sync to ingest recovery, sleep, cycles, workouts, and body measurements."
        elif self.settings.whoop_client_id and self.settings.whoop_client_secret:
            status = ConnectorStatus.CONFIGURED
            next_action = "Visit /auth/whoop/start to authorize offline access."
        else:
            status = ConnectorStatus.MISSING_CREDENTIALS
            next_action = "Create a WHOOP developer app, set client credentials, and include the offline scope."
        return ConnectorInfo(
            name=self.name,
            status=status,
            detail="Official WHOOP OAuth 2.0 API connector. The offline scope is required for refresh tokens.",
            next_action=next_action,
            official_docs_url=self.docs_url,
        )

    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.settings.whoop_client_id,
            "redirect_uri": self.settings.whoop_redirect_uri,
            "response_type": "code",
            "scope": WHOOP_SCOPES,
            "state": state[:8],
        }
        return f"{WHOOP_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.settings.whoop_client_id,
            "client_secret": self.settings.whoop_client_secret,
            "redirect_uri": self.settings.whoop_redirect_uri,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(WHOOP_TOKEN_URL, data=data)
            response.raise_for_status()
            return response.json()

    async def refresh_access_token(self, refresh_token: str) -> dict:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.settings.whoop_client_id,
            "client_secret": self.settings.whoop_client_secret,
            "scope": "offline",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(WHOOP_TOKEN_URL, data=data)
            response.raise_for_status()
            return response.json()

    async def fetch_collection(self, access_token: str, path: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{WHOOP_API_BASE}{path}", headers={"Authorization": f"Bearer {access_token}"}, params=params)
            response.raise_for_status()
            return response.json()

    async def fetch_paginated_collection(self, access_token: str, path: str, params: dict | None = None) -> list[dict]:
        records: list[dict] = []
        request_params = dict(params or {})
        while True:
            payload = await self.fetch_collection(access_token, path, request_params)
            records.extend(payload.get("records") or [])
            next_token = payload.get("next_token")
            if not next_token:
                return records
            request_params["nextToken"] = next_token


def token_expiry(token_payload: dict) -> datetime | None:
    expires_in = token_payload.get("expires_in")
    if expires_in is None:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
