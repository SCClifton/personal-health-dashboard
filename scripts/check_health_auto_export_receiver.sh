#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

port="${PORT:-8000}"
wifi_ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
hostname_url="http://$(scutil --get LocalHostName 2>/dev/null || hostname -s).local:${port}"
db_path="${HEALTH_DASHBOARD_DB:-data/health_dashboard.db}"
max_age_hours="${MAX_APPLE_HEALTH_AGE_HOURS:-30}"

echo "Local health check:"
curl -fsS "http://127.0.0.1:${port}/health"
echo

if [[ -n "$wifi_ip" ]]; then
  echo "Wi-Fi URL for Health Auto Export:"
  echo "http://${wifi_ip}:${port}/ingest/apple-health"
  echo "Wi-Fi health check:"
  curl -fsS "http://${wifi_ip}:${port}/health"
  echo
fi

echo "mDNS URL to try if the iPhone resolves local hostnames:"
echo "${hostname_url}/ingest/apple-health"

secret="${HEALTH_AUTO_EXPORT_SHARED_SECRET:-}"
if [[ -z "$secret" && -f .env ]]; then
  secret="$(python3 - <<'PY'
from pathlib import Path

for line in Path(".env").read_text().splitlines():
    if line.startswith("HEALTH_AUTO_EXPORT_SHARED_SECRET="):
        print(line.split("=", 1)[1].strip().strip('"').strip("'"))
        break
PY
)"
fi

if [[ -n "$secret" ]]; then
  echo "Shared-secret verification:"
  SECRET="$secret" PORT="$port" python3 - <<'PY'
import json
import os
import urllib.error
import urllib.request

request = urllib.request.Request(
    f"http://127.0.0.1:{os.environ['PORT']}/ingest/apple-health/verify",
    headers={"Authorization": "Bearer " + os.environ["SECRET"]},
)
try:
    with urllib.request.urlopen(request, timeout=5) as response:
        print(json.loads(response.read().decode()))
except urllib.error.HTTPError as exc:
    raise SystemExit(f"verify failed: HTTP {exc.code}") from exc
PY
else
  echo "Shared-secret verification skipped: HEALTH_AUTO_EXPORT_SHARED_SECRET not loaded and not present in .env."
fi

echo "Recent Apple Health ingest state:"
sqlite3 "$db_path" "SELECT COUNT(*), MAX(received_at), MAX(observed_start) FROM raw_events WHERE provider='apple_health';"

MAX_AGE_HOURS="$max_age_hours" DB_PATH="$db_path" python3 - <<'PY'
from __future__ import annotations

import datetime as dt
import os
import sqlite3

max_age_hours = float(os.environ["MAX_AGE_HOURS"])
with sqlite3.connect(os.environ["DB_PATH"]) as db:
    latest = db.execute(
        "SELECT MAX(received_at) FROM raw_events WHERE provider='apple_health'"
    ).fetchone()[0]
if not latest:
    print("Freshness warning: no Apple Health ingest has been received yet.")
    raise SystemExit(2 if os.environ.get("FAIL_ON_STALE") == "1" else 0)
latest_dt = dt.datetime.fromisoformat(latest)
if latest_dt.tzinfo is None:
    latest_dt = latest_dt.replace(tzinfo=dt.timezone.utc)
age_hours = (dt.datetime.now(dt.timezone.utc) - latest_dt.astimezone(dt.timezone.utc)).total_seconds() / 3600
print(f"Apple Health ingest age: {age_hours:.1f} hours")
if age_hours > max_age_hours:
    print(f"Freshness warning: Apple Health ingest is older than {max_age_hours:g} hours.")
    raise SystemExit(2 if os.environ.get("FAIL_ON_STALE") == "1" else 0)
PY

echo "Generate a fresh minimal Health Auto Export deep link:"
echo "scripts/generate_health_auto_export_deeplink.py --host ${wifi_ip:-<host>} --enabled"
