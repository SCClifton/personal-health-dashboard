#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from urllib.parse import quote


DEFAULT_METRICS = [
    "Step Count",
    "Heart Rate",
    "Active Energy",
    "Resting Heart Rate",
    "Heart Rate Variability",
]


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"').strip("'")
    return values


def local_wifi_ip() -> str | None:
    try:
        result = subprocess.run(
            ["ipconfig", "getifaddr", "en0"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    value = result.stdout.strip()
    return value or None


def build_url(args: argparse.Namespace, secret: str) -> str:
    host = args.host or local_wifi_ip()
    if not host:
        raise SystemExit("Could not determine Wi-Fi IP. Pass --host explicitly.")
    endpoint = args.endpoint or f"http://{host}:{args.port}/ingest/apple-health"
    params = {
        "url": endpoint,
        "name": args.name,
        "format": "json",
        "datatype": "healthMetrics",
        "period": args.period,
        "interval": "days",
        "aggregatedata": "true",
        "aggregatesleep": "true",
        "exportversion": "v2",
        "syncinterval": "days",
        "syncquantity": "1",
        "metrics": ",".join(args.metrics),
        "headers": f"Authorization,Bearer {secret}",
        "requesttimeout": str(args.request_timeout),
        "batchrequests": "true",
        "notifyonupdate": "true",
        "notifywhenrun": "true",
        "enabled": "true" if args.enabled else "false",
    }
    return "com.HealthExport://automation?" + "&".join(
        f"{key}={quote(value, safe=',:/')}" for key, value in params.items()
    )


def copy_to_clipboard(value: str) -> None:
    subprocess.run(["pbcopy"], input=value.encode(), check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Health Auto Export REST automation deep link without printing secrets."
    )
    parser.add_argument("--env-file", default=".env", help="Env file containing HEALTH_AUTO_EXPORT_SHARED_SECRET.")
    parser.add_argument("--host", help="Mac host/IP reachable from the iPhone. Defaults to en0 Wi-Fi IP.")
    parser.add_argument("--port", default="8000", help="Dashboard port.")
    parser.add_argument("--endpoint", help="Full /ingest/apple-health endpoint URL.")
    parser.add_argument("--name", default="Personal Health App Codex Current")
    parser.add_argument(
        "--period",
        default="today",
        choices=["none", "lastsync", "today", "yesterday", "previous7days", "realtime"],
        help="Health Auto Export date range.",
    )
    parser.add_argument("--metric", dest="metrics", action="append", help="Health Auto Export metric name. Repeatable.")
    parser.add_argument("--request-timeout", type=int, default=300)
    parser.add_argument("--enabled", action="store_true", help="Create the automation enabled.")
    parser.add_argument("--print-redacted", action="store_true", help="Print a redacted link for review.")
    parser.add_argument("--no-copy", action="store_true", help="Do not copy the real deep link to the clipboard.")
    args = parser.parse_args()

    dotenv = load_dotenv(Path(args.env_file))
    secret = os.environ.get("HEALTH_AUTO_EXPORT_SHARED_SECRET") or dotenv.get("HEALTH_AUTO_EXPORT_SHARED_SECRET")
    if not secret:
        raise SystemExit("HEALTH_AUTO_EXPORT_SHARED_SECRET is missing.")
    args.metrics = args.metrics or DEFAULT_METRICS

    url = build_url(args, secret)
    if not args.no_copy:
        copy_to_clipboard(url)
        print("Copied Health Auto Export deep link to clipboard.")
    if args.print_redacted:
        print(url.replace(secret, "<redacted>"))


if __name__ == "__main__":
    main()
