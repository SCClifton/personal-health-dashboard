#!/usr/bin/env bash
set -euo pipefail

# Run a local health-report command with all known Personal Health Dashboard
# provider API credentials loaded from 1Password into this process only.
#
# Usage:
#   scripts/run_health_report_with_op_env.sh
#   scripts/run_health_report_with_op_env.sh .venv/bin/python scripts/auto_health_report.py --sync-days 14

cd "$(dirname "$0")/.."

source scripts/load_health_op_env.sh

if [[ "$#" -eq 0 ]]; then
  set -- .venv/bin/python scripts/auto_health_report.py
fi

PYTHONPATH="${PYTHONPATH:-src}"
export PYTHONPATH

exec "$@"
