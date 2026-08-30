#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from health_dashboard.config import Settings
from health_dashboard.connectors.health_auto_export_mcp import (
    MCP_TOOL_NAMES,
    HealthAutoExportMcpClient,
    HealthAutoExportMcpError,
    chunk_date_ranges,
    headers_from_helper,
    import_mcp_payload,
    payload_item_count,
    tool_arguments,
)
from health_dashboard.db import _configure_sqlite_engine, _engine_kwargs


DEFAULT_ENDPOINT = "http://192.168.4.110:9000/mcp"
DEFAULT_HEADERS_HELPER = "~/.local/bin/health-auto-export-mcp-headers"


def parse_args() -> argparse.Namespace:
    settings = Settings()
    parser = argparse.ArgumentParser(
        description="Backfill the local health dashboard from Health Auto Export's authenticated MCP server."
    )
    parser.add_argument("--start", required=True, type=date.fromisoformat, help="First local date, YYYY-MM-DD.")
    parser.add_argument("--end", type=date.fromisoformat, default=date.today(), help="Last local date, YYYY-MM-DD.")
    parser.add_argument("--chunk-days", type=int, default=7, help="Days per MCP request (default: 7).")
    parser.add_argument(
        "--tool",
        action="append",
        choices=MCP_TOOL_NAMES,
        dest="tools",
        help="MCP category to fetch. Repeat to select several; default is every category.",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("HEALTH_AUTO_EXPORT_MCP_URL", DEFAULT_ENDPOINT),
        help="Health Auto Export MCP endpoint.",
    )
    parser.add_argument(
        "--headers-helper",
        default=os.environ.get("HEALTH_AUTO_EXPORT_MCP_HEADERS_HELPER", DEFAULT_HEADERS_HELPER),
        help="Executable that emits authenticated HTTP headers as JSON.",
    )
    parser.add_argument("--database-url", default=settings.database_url, help="Dashboard SQLAlchemy database URL.")
    parser.add_argument("--timezone", default=settings.local_timezone, help="HealthKit local timezone.")
    parser.add_argument(
        "--raw-metrics",
        action="store_true",
        help="Request non-aggregated metric points. Daily aggregation is the safer default for catch-up.",
    )
    parser.add_argument(
        "--include-workout-routes",
        action="store_true",
        help="Include detailed workout routes in the local raw archive.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate payloads without writing the database.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tools = tuple(args.tools or MCP_TOOL_NAMES)
    engine = create_engine(args.database_url, future=True, **_engine_kwargs(args.database_url))
    _configure_sqlite_engine(engine, args.database_url)
    totals = {
        "chunks": 0,
        "envelopes_imported": 0,
        "envelope_duplicates": 0,
        "metric_points_imported": 0,
        "metric_point_duplicates": 0,
    }
    headers_helper = Path(args.headers_helper).expanduser()

    try:
        with HealthAutoExportMcpClient(
            args.endpoint,
            headers_provider=lambda: headers_from_helper(headers_helper),
        ) as client:
            with Session(engine) as db:
                for chunk_start, chunk_end in chunk_date_ranges(args.start, args.end, chunk_days=args.chunk_days):
                    for tool_name in tools:
                        arguments = tool_arguments(
                            tool_name,
                            start=chunk_start,
                            end=chunk_end,
                            timezone_name=args.timezone,
                            aggregate_metrics=not args.raw_metrics,
                            include_workout_routes=args.include_workout_routes,
                        )
                        payload = client.call_tool(tool_name, arguments)
                        item_count = payload_item_count(tool_name, payload)
                        totals["chunks"] += 1
                        if args.dry_run:
                            print(f"validated tool={tool_name} start={chunk_start} end={chunk_end} records={item_count}")
                            continue
                        result = import_mcp_payload(
                            db,
                            tool_name=tool_name,
                            arguments=arguments,
                            payload=payload,
                            timezone_name=args.timezone,
                        )
                        db.commit()
                        totals["envelopes_imported"] += result.envelope_imported
                        totals["envelope_duplicates"] += result.envelope_duplicates
                        totals["metric_points_imported"] += result.metric_points_imported
                        totals["metric_point_duplicates"] += result.metric_point_duplicates
                        print(
                            f"synced tool={tool_name} start={chunk_start} end={chunk_end} "
                            f"raw={result.envelope_imported} metrics={result.metric_points_imported} "
                            f"duplicates={result.envelope_duplicates + result.metric_point_duplicates}"
                        )
    except HealthAutoExportMcpError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        engine.dispose()

    mode = "validated" if args.dry_run else "synced"
    print(
        f"{mode} chunks={totals['chunks']} raw_imported={totals['envelopes_imported']} "
        f"raw_duplicates={totals['envelope_duplicates']} metric_points_imported={totals['metric_points_imported']} "
        f"metric_point_duplicates={totals['metric_point_duplicates']}"
    )


if __name__ == "__main__":
    main()
