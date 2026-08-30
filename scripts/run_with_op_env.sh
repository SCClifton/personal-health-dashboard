#!/usr/bin/env bash
set -euo pipefail

# Loads environment variables from a 1Password item, then runs the provided command.
# Secrets stay in the child process environment and are not printed by this script.
#
# Usage:
#   OP_ACCOUNT="my.1password.com" OP_VAULT="Catherine & Sam" OP_ITEM="Personal Health Dashboard Whoop API" scripts/run_with_op_env.sh
#   OP_ITEM="Personal Health Dashboard Whoop API" scripts/run_with_op_env.sh
#   OP_ITEM="Personal Health Dashboard Whoop API" scripts/run_with_op_env.sh curl -s http://127.0.0.1:8000/api/connectors

cd "$(dirname "$0")/.."

source scripts/load_op_env.sh

if [[ "$#" -eq 0 ]]; then
  set -- .venv/bin/python -m uvicorn health_dashboard.main:app --host 0.0.0.0 --port 8000
fi

PYTHONPATH="${PYTHONPATH:-src}"
export PYTHONPATH

exec "$@"
