#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export PYTHONPATH="${PYTHONPATH:-src}"

source scripts/health_network_mode.sh

port="${PORT:-8000}"
poll_seconds="${HEALTH_DASHBOARD_NETWORK_POLL_SECONDS:-3}"
child_pid=""

stop_child() {
  if [[ -n "$child_pid" ]] && kill -0 "$child_pid" 2>/dev/null; then
    kill -TERM "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
}

shutdown() {
  stop_child
  exit 0
}

trap shutdown INT TERM

while true; do
  mode="$(health_network_mode)"
  bind_host="$(health_bind_host "$mode")"
  echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Starting health dashboard: $(health_network_summary) port=${port}"

  .venv/bin/python -m uvicorn health_dashboard.main:app --host "$bind_host" --port "$port" &
  child_pid=$!
  restart_for_network=0

  while kill -0 "$child_pid" 2>/dev/null; do
    sleep "$poll_seconds" &
    wait $! || true

    next_mode="$(health_network_mode)"
    next_bind_host="$(health_bind_host "$next_mode")"
    if [[ "$next_bind_host" != "$bind_host" ]]; then
      echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Network trust changed: ${mode}/${bind_host} -> ${next_mode}/${next_bind_host}"
      restart_for_network=1
      stop_child
      break
    fi
  done

  if [[ "$restart_for_network" == "1" ]]; then
    child_pid=""
    continue
  fi

  if wait "$child_pid"; then
    status=0
  else
    status=$?
  fi
  child_pid=""
  echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Health dashboard exited unexpectedly with status ${status}."
  exit "$status"
done
