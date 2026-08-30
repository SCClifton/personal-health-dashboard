#!/usr/bin/env bash
set -euo pipefail

# Non-revealing 1Password field check.
#
# Usage:
#   OP_ITEM="Personal Health Dashboard Whoop API" scripts/check_op_env.sh
#   OP_ACCOUNT="my.1password.com" OP_VAULT="Catherine & Sam" OP_ITEM="Personal Health Dashboard Whoop API" scripts/check_op_env.sh
#   OP_VAULT="Clifton Family" OP_ITEM="Personal Health Dashboard Whoop API" scripts/check_op_env.sh WHOOP_CLIENT_ID WHOOP_CLIENT_SECRET

if ! command -v op >/dev/null 2>&1; then
  echo "1Password CLI 'op' is not installed or not on PATH." >&2
  exit 1
fi

OP_ITEM="${OP_ITEM:-Personal Health Dashboard}"
OP_ARGS=()
if [[ -n "${OP_ACCOUNT:-}" ]]; then
  OP_ARGS+=(--account "$OP_ACCOUNT")
fi
if [[ -n "${OP_VAULT:-}" ]]; then
  OP_ARGS+=(--vault "$OP_VAULT")
fi

if [[ "$#" -gt 0 ]]; then
  keys=("$@")
else
  keys=(WHOOP_CLIENT_ID WHOOP_CLIENT_SECRET WHOOP_REDIRECT_URI)
fi

item_json="$(op item get "$OP_ITEM" ${OP_ARGS+"${OP_ARGS[@]}"} --format json)"
missing=()
for key in "${keys[@]}"; do
  value="$(printf '%s' "$item_json" | jq -r --arg key "$key" '[.fields[]? | select(.label == $key) | .value][0] // empty')"
  if [[ -n "$value" ]]; then
    printf '%s=set\n' "$key"
  else
    printf '%s=missing\n' "$key"
    missing+=("$key")
  fi
done

if [[ "${#missing[@]}" -gt 0 ]]; then
  echo "Missing required 1Password fields: ${missing[*]}" >&2
  exit 1
fi
