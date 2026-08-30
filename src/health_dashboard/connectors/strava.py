from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from health_dashboard.config import Settings
from health_dashboard.connectors.base import ConnectorInfo, ConnectorStatus
from health_dashboard.models import OAuthToken


STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_SCOPES = "read,activity:read_all,profile:read_all"
STRAVA_RUN_STREAM_KEYS = ["time", "distance", "heartrate", "cadence", "velocity_smooth", "altitude", "moving"]


class StravaConnector:
    name = "strava"
    docs_url = "https://developers.strava.com/"

    def __init__(self, settings: Settings, token: OAuthToken | None = None) -> None:
        self.settings = settings
        self.token = token

    def status(self) -> ConnectorInfo:
        if self.token and self.token.access_token:
            status = ConnectorStatus.CONNECTED
            next_action = "Run a Strava sync and optionally register /webhooks/strava."
        elif self.settings.strava_client_id and self.settings.strava_client_secret:
            status = ConnectorStatus.CONFIGURED
            next_action = "Visit /auth/strava/start to authorize activities and streams."
        else:
            status = ConnectorStatus.MISSING_CREDENTIALS
            next_action = "Create/manage a Strava app, then set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET."
        return ConnectorInfo(
            name=self.name,
            status=status,
            detail="Official Strava API connector for athlete profile, activities, streams, and webhook event intake.",
            next_action=next_action,
            official_docs_url=self.docs_url,
        )

    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.settings.strava_client_id,
            "redirect_uri": self.settings.strava_redirect_uri,
            "response_type": "code",
            "approval_prompt": "auto",
            "scope": STRAVA_SCOPES,
            "state": state,
        }
        return f"{STRAVA_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        data = {
            "client_id": self.settings.strava_client_id,
            "client_secret": self.settings.strava_client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(STRAVA_TOKEN_URL, data=data)
            response.raise_for_status()
            return response.json()

    async def refresh_access_token(self, refresh_token: str) -> dict:
        data = {
            "client_id": self.settings.strava_client_id,
            "client_secret": self.settings.strava_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(STRAVA_TOKEN_URL, data=data)
            response.raise_for_status()
            return response.json()

    async def fetch_activities_page(self, access_token: str, after: int | None = None, before: int | None = None, page: int = 1) -> list[dict]:
        params = {"per_page": 200, "page": page}
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{STRAVA_API_BASE}/athlete/activities", headers={"Authorization": f"Bearer {access_token}"}, params=params)
            response.raise_for_status()
            return response.json()

    async def fetch_activities(self, access_token: str, after: int | None = None, before: int | None = None) -> list[dict]:
        activities: list[dict] = []
        page = 1
        while True:
            batch = await self.fetch_activities_page(access_token, after=after, before=before, page=page)
            if not batch:
                return activities
            activities.extend(batch)
            page += 1

    async def fetch_activity_detail(self, access_token: str, activity_id: int, *, include_all_efforts: bool = False) -> dict:
        params = {"include_all_efforts": str(include_all_efforts).lower()}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{STRAVA_API_BASE}/activities/{activity_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            response.raise_for_status()
            return response.json()

    async def fetch_laps(self, access_token: str, activity_id: int) -> list[dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{STRAVA_API_BASE}/activities/{activity_id}/laps",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()

    async def fetch_streams(self, access_token: str, activity_id: int, keys: list[str] | None = None) -> dict:
        params = {"keys": ",".join(keys or STRAVA_RUN_STREAM_KEYS), "key_by_type": "true"}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{STRAVA_API_BASE}/activities/{activity_id}/streams",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            response.raise_for_status()
            return response.json()


def strava_token_expiry(token_payload: dict) -> datetime | None:
    expires_at = token_payload.get("expires_at")
    if expires_at:
        return datetime.fromtimestamp(int(expires_at), tz=timezone.utc)
    expires_in = token_payload.get("expires_in")
    if expires_in:
        return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    return None


def verify_strava_signature(raw_body: bytes, header: str | None, signing_secret: str | None, tolerance_seconds: int = 300) -> bool:
    if not signing_secret:
        return True
    if not header:
        return False
    try:
        parts = dict(part.split("=", 1) for part in header.split(","))
        timestamp = int(parts["t"])
        signature = parts["v1"]
    except (KeyError, ValueError):
        return False
    if abs(time.time() - timestamp) > tolerance_seconds:
        return False
    expected = hmac.new(signing_secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
