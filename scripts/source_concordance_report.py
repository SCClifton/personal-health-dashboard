#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from health_dashboard.config import get_settings
from health_dashboard.db import SessionLocal, init_db
from health_dashboard.services.source_concordance import build_source_concordance_report, render_source_concordance_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a local source-concordance report for HRV and sleep sources.")
    parser.add_argument("--days", type=int, default=90, help="Lookback window in days.")
    parser.add_argument("--out", default=str(ROOT / "local_exports" / "source_concordance"), help="Output directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    init_db()
    settings = get_settings()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        report = build_source_concordance_report(db, days=args.days, tz_name=settings.local_timezone)

    stamp = report["generated_at"][:10]
    json_path = out_dir / f"source_concordance_{stamp}.json"
    md_path = out_dir / f"source_concordance_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_source_concordance_markdown(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
