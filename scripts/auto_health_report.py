#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from health_dashboard.config import get_settings
from health_dashboard.db import SessionLocal, init_db
from health_dashboard.services.auto_report import build_auto_health_report, render_auto_health_report_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync connected health APIs and write a local daily health check-in.")
    parser.add_argument("--days", type=int, default=90, help="Daily feature lookback window for report summaries.")
    parser.add_argument("--sync-days", type=int, default=14, help="Connected API lookback window for WHOOP and Strava syncs.")
    parser.add_argument("--no-sync", action="store_true", help="Skip WHOOP/Strava syncs and only report local SQLite state.")
    parser.add_argument("--date", type=date.fromisoformat, default=None, help="Report date in YYYY-MM-DD format. Defaults to local today.")
    parser.add_argument("--out", default=str(ROOT / "local_exports" / "health_checkins"), help="Output directory.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    init_db()
    settings = get_settings()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        report = await build_auto_health_report(
            db,
            settings,
            days=args.days,
            sync=not args.no_sync,
            sync_days=args.sync_days,
            report_date=args.date,
        )

    report_date = report["report_date"]
    json_path = out_dir / f"health_checkin_{report_date}.json"
    md_path = out_dir / f"health_checkin_{report_date}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_auto_health_report_markdown(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    asyncio.run(main())
