#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   OP_ITEM="Personal Health Dashboard" source scripts/load_op_env.sh
#   OP_ACCOUNT="my.1password.com" OP_VAULT="Catherine & Sam" OP_ITEM="Personal Health Dashboard Whoop API" source scripts/load_op_env.sh
#   OP_VAULT="Clifton Family" OP_ITEM="Personal Health Dashboard Whoop API" source scripts/load_op_env.sh
#   OP_KEYS="WHOOP_CLIENT_ID WHOOP_CLIENT_SECRET WHOOP_REDIRECT_URI" OP_ITEM="Personal Health Dashboard Whoop API" source scripts/load_op_env.sh
#
# Expected 1Password item fields use the same names as .env.example.

if ! command -v op >/dev/null 2>&1; then
  echo "1Password CLI 'op' is not installed or not on PATH." >&2
  return 1 2>/dev/null || exit 1
fi

OP_ITEM="${OP_ITEM:-Personal Health Dashboard}"
OP_ARGS=()
if [[ -n "${OP_ACCOUNT:-}" ]]; then
  OP_ARGS+=(--account "$OP_ACCOUNT")
fi
if [[ -n "${OP_VAULT:-}" ]]; then
  OP_ARGS+=(--vault "$OP_VAULT")
fi

if [[ -n "${OP_KEYS:-}" ]]; then
  keys=()
  while IFS= read -r key; do
    [[ -n "$key" ]] && keys+=("$key")
  done < <(printf '%s\n' "$OP_KEYS" | tr ', ' '\n\n')
else
  keys=()
  while IFS= read -r key; do
    keys+=("$key")
  done < <(grep -E '^[A-Z0-9_]+=' .env.example | cut -d= -f1)
fi

item_json="$(op item get "$OP_ITEM" ${OP_ARGS+"${OP_ARGS[@]}"} --format json)"
for key in "${keys[@]}"; do
  value="$(printf '%s' "$item_json" | jq -r --arg key "$key" '[.fields[]? | select(.label == $key) | .value][0] // empty')"
  if [[ -n "$value" ]]; then
    export "$key=$value"
  fi
done
