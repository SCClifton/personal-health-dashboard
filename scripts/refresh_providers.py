#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from health_dashboard.config import get_settings
from health_dashboard.db import SessionLocal, init_db
from health_dashboard.services.oura_sync import sync_oura
from health_dashboard.services.strava_sync import sync_strava
from health_dashboard.services.sync_queue import provider_sync_slot
from health_dashboard.services.whoop_sync import sync_whoop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh connected health providers without printing health values or credentials.")
    parser.add_argument("--days", type=int, default=7, help="Idempotent overlap window for each provider.")
    return parser.parse_args()


def safe_result(provider: str, result: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {
        "provider": provider,
        "status": "synced",
        "imported": int(result.get("imported") or 0),
        "duplicates": int(result.get("duplicates") or 0),
    }
    collections = result.get("collections")
    if isinstance(collections, dict):
        output["collections"] = {
            name: {key: value for key, value in details.items() if key in {"imported", "duplicates", "error"}}
            for name, details in collections.items()
            if isinstance(details, dict)
        }
    return output


async def main() -> None:
    args = parse_args()
    if args.days < 1 or args.days > 30:
        raise SystemExit("--days must be between 1 and 30")

    init_db()
    settings = get_settings()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    results: list[dict[str, Any]] = []

    with SessionLocal() as db:
        for provider, sync_func in (("whoop", sync_whoop), ("strava", sync_strava), ("oura", sync_oura)):
            try:
                async with provider_sync_slot(provider):
                    result = await sync_func(db, settings, start=start, end=end)
                db.commit()
                results.append(safe_result(provider, result))
            except ValueError as exc:
                db.rollback()
                results.append({"provider": provider, "status": "skipped", "detail": str(exc)})
            except httpx.HTTPStatusError as exc:
                db.rollback()
                results.append({"provider": provider, "status": "error", "detail": f"HTTP {exc.response.status_code}"})
            except Exception as exc:  # keep other providers retryable after one unexpected failure
                db.rollback()
                results.append({"provider": provider, "status": "error", "detail": type(exc).__name__})

    print(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "window_days": args.days, "results": results}, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
