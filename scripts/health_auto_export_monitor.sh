#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

source scripts/health_network_mode.sh

port="${PORT:-8000}"
max_age_hours="${MAX_APPLE_HEALTH_AGE_HOURS:-30}"
expected_repo_dir="${EXPECTED_REPO_DIR:-$(pwd)}"
db_path="${HEALTH_DASHBOARD_DB:-data/health_dashboard.db}"
log_dir="${HEALTH_AUTO_EXPORT_MONITOR_LOG_DIR:-logs}"
state_file="${HEALTH_AUTO_EXPORT_MONITOR_STATE:-${log_dir}/health-auto-export-monitor.state}"

mkdir -p "$log_dir"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

notify() {
  local title="$1"
  local body="$2"
  NOTIFY_TITLE="$title" NOTIFY_BODY="$body" osascript <<'APPLESCRIPT' >/dev/null 2>&1 || true
display notification (system attribute "NOTIFY_BODY") with title (system attribute "NOTIFY_TITLE")
APPLESCRIPT
}

fail() {
  local message="$1"
  echo "[$(timestamp)] ERROR: ${message}" >&2
  notify "Health Auto Export needs attention" "$message"
  exit 2
}

write_state() {
  local mode="$1"
  local wifi_ip="$2"
  local router="$3"
  local tmp_state="${state_file}.$$"
  {
    echo "checked_at=$(timestamp)"
    echo "network_mode=${mode}"
    echo "wifi_ip=${wifi_ip}"
    echo "router=${router}"
    echo "port=${port}"
    echo "repo_dir=${expected_repo_dir}"
    echo "db_path=${db_path}"
  } >"$tmp_state"
  mv "$tmp_state" "$state_file"
}

mode="$(health_network_mode)"
wifi_ip="$(health_wifi_ip)"
router="$(health_default_router)"

port_pids="$(lsof -nP -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null | tr '\n' ' ')"
if [[ -z "$port_pids" ]]; then
  fail "No dashboard receiver is listening on port ${port}."
fi

owner_ok=0
owner_summary=""
for pid in $port_pids; do
  cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
  owner_summary+="${pid}:${cwd:-unknown} "
  if [[ "$cwd" == "$expected_repo_dir" ]]; then
    owner_ok=1
  fi
done

if [[ "$owner_ok" != "1" ]]; then
  fail "Port ${port} is not owned by ${expected_repo_dir}. Current owner(s): ${owner_summary}"
fi

if ! curl -fsS --max-time 5 "http://127.0.0.1:${port}/health" >/dev/null; then
  fail "The loopback dashboard health check failed on port ${port}."
fi

if [[ "$mode" != "home" ]]; then
  listener_names="$(lsof -nP -iTCP:"${port}" -sTCP:LISTEN -Fn 2>/dev/null | sed -n 's/^n//p')"
  bad_listener=""
  while IFS= read -r listener_name; do
    [[ -z "$listener_name" ]] && continue
    case "$listener_name" in
      "127.0.0.1:${port}") ;;
      *) bad_listener="$listener_name" ;;
    esac
  done <<<"$listener_names"

  if [[ -n "$bad_listener" ]]; then
    fail "Away from home but port ${port} is exposed as ${bad_listener}; expected loopback-only binding."
  fi
fi

case "$mode" in
  away)
    write_state "$mode" "${wifi_ip:-none}" "${router:-none}"
    echo "[$(timestamp)] Away from home: receiver is loopback-only; Health Auto Export is deferred until home."
    exit 0
    ;;
  no_wifi)
    write_state "$mode" "none" "none"
    echo "[$(timestamp)] No Wi-Fi: receiver is loopback-only; Health Auto Export is deferred until home."
    exit 0
    ;;
  home_unreserved)
    write_state "$mode" "${wifi_ip:-none}" "${router:-none}"
    fail "The home gateway address was detected, but neither the configured router identity nor reserved address matched. Keep macOS on DHCP and verify HEALTH_DASHBOARD_HOME_ROUTER_MAC."
    ;;
esac

if ! HEALTH_DASHBOARD_DB="$db_path" \
  FAIL_ON_STALE=1 \
  MAX_APPLE_HEALTH_AGE_HOURS="$max_age_hours" \
  PORT="$port" \
  scripts/check_health_auto_export_receiver.sh; then
  fail "Home receiver check failed or Apple Health is older than ${max_age_hours} hours. Expected URL: http://${wifi_ip}:${port}/ingest/apple-health"
fi

write_state "$mode" "$wifi_ip" "$router"
echo "[$(timestamp)] Health Auto Export monitor OK at home: http://${wifi_ip}:${port}/ingest/apple-health"
