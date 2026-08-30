from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data/health_dashboard.db"
    app_base_url: str = "http://localhost:8000"
    app_secret_key: str = "local-dev-change-me"
    local_timezone: str = "Australia/Sydney"
    health_auto_export_shared_secret: Optional[str] = None
    height_cm: Optional[float] = None

    whoop_client_id: Optional[str] = None
    whoop_client_secret: Optional[str] = None
    whoop_redirect_uri: str = "http://localhost:8000/auth/whoop/callback"

    strava_client_id: Optional[str] = None
    strava_client_secret: Optional[str] = None
    strava_redirect_uri: str = "http://localhost:8000/auth/strava/callback"
    strava_webhook_verify_token: Optional[str] = None
    strava_webhook_signing_secret: Optional[str] = None

    oura_client_id: Optional[str] = None
    oura_client_secret: Optional[str] = None
    oura_redirect_uri: str = "http://localhost:8000/auth/oura/callback"
    oura_personal_access_token: Optional[str] = None

    garmin_client_id: Optional[str] = None
    garmin_client_secret: Optional[str] = None
    garmin_redirect_uri: str = "http://localhost:8000/auth/garmin/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
