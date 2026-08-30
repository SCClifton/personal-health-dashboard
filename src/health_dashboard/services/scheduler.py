from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from health_dashboard.config import get_settings
from health_dashboard.db import SessionLocal
from health_dashboard.services.ingestion import rebuild_daily_features
from health_dashboard.services.sync_queue import provider_sync_slot
from health_dashboard.services.whoop_sync import sync_whoop

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(_rebuild_daily_features_job, "interval", hours=6, id="rebuild_daily_features", replace_existing=True)
    _scheduler.add_job(_sync_whoop_job, "interval", hours=6, id="sync_whoop", replace_existing=True)
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def _rebuild_daily_features_job() -> None:
    try:
        with SessionLocal() as db:
            rebuild_daily_features(db)
            db.commit()
    except Exception:
        logger.exception("Scheduled daily feature rebuild failed")


def _sync_whoop_job() -> None:
    settings = get_settings()
    if not settings.whoop_client_id or not settings.whoop_client_secret:
        logger.info("Scheduled WHOOP sync skipped because client credentials are not configured")
        return
    try:
        asyncio.run(_sync_whoop_recent(settings))
    except Exception:
        logger.exception("Scheduled WHOOP sync failed")


async def _sync_whoop_recent(settings) -> None:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    async with provider_sync_slot("whoop"):
        with SessionLocal() as db:
            sync_result = await sync_whoop(db, settings, start=start, end=end)
            db.commit()
            logger.info(
                "Scheduled WHOOP sync imported %s records and skipped %s duplicates",
                sync_result["imported"],
                sync_result["duplicates"],
            )
