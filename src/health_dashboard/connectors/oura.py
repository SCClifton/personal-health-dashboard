from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from health_dashboard.config import Settings
from health_dashboard.connectors.base import ConnectorInfo, ConnectorStatus
from health_dashboard.models import OAuthToken


OURA_AUTH_URL = "https://cloud.ouraring.com/oauth/authorize"
OURA_TOKEN_URL = "https://api.ouraring.com/oauth/token"
OURA_API_BASE = "https://api.ouraring.com/v2/usercollection"
OURA_SCOPES = "personal daily heartrate workout tag session spo2"


class OuraConnector:
    name = "oura"
    docs_url = "https://cloud.ouraring.com/docs/"

    def __init__(self, settings: Settings, token: OAuthToken | None = None) -> None:
        self.settings = settings
        self.token = token

    def status(self) -> ConnectorInfo:
        if (self.token and self.token.access_token) or self.settings.oura_personal_access_token:
            status = ConnectorStatus.CONNECTED
            next_action = "Run an Oura sync for sleep, readiness, activity, heart rate, SpO2, stress, resilience, and device context."
        elif self.settings.oura_client_id and self.settings.oura_client_secret:
            status = ConnectorStatus.CONFIGURED
            next_action = "Visit /auth/oura/start to authorize local OAuth access."
        else:
            status = ConnectorStatus.MISSING_CREDENTIALS
            next_action = "Create an Oura developer app, set client credentials, and use OAuth authorization."
        return ConnectorInfo(
            name=self.name,
            status=status,
            detail="Official Oura API v2 connector using OAuth2. Personal access token support is legacy/local fallback only.",
            next_action=next_action,
            official_docs_url=self.docs_url,
        )

    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.settings.oura_client_id,
            "redirect_uri": self.settings.oura_redirect_uri,
            "response_type": "code",
            "scope": OURA_SCOPES,
            "state": state,
        }
        return f"{OURA_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.settings.oura_client_id,
            "client_secret": self.settings.oura_client_secret,
            "redirect_uri": self.settings.oura_redirect_uri,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(OURA_TOKEN_URL, data=data)
            response.raise_for_status()
            return response.json()

    async def refresh_access_token(self, refresh_token: str) -> dict:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.settings.oura_client_id,
            "client_secret": self.settings.oura_client_secret,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(OURA_TOKEN_URL, data=data)
            response.raise_for_status()
            return response.json()

    async def fetch_collection(self, access_token: str, collection: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{OURA_API_BASE}/{collection}",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            response.raise_for_status()
            return response.json()

    async def fetch_paginated_collection(self, access_token: str, collection: str, params: dict | None = None) -> list[dict]:
        records: list[dict] = []
        request_params = dict(params or {})
        while True:
            payload = await self.fetch_collection(access_token, collection, request_params)
            records.extend(payload.get("data") or [])
            next_token = payload.get("next_token")
            if not next_token:
                return records
            request_params["next_token"] = next_token


def oura_token_expiry(token_payload: dict) -> datetime | None:
    expires_in = token_payload.get("expires_in")
    if expires_in:
        return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    return None
