#!/usr/bin/env bash
set -euo pipefail

# Load Personal Health Dashboard provider credentials from their current
# 1Password items without printing secret values. Source this file from another
# shell/script when the exported variables need to persist in that process.
#
# Current known project items:
#   WHOOP:  Catherine & Sam / Personal Health Dashboard Whoop API
#   Strava: Private / Strava API Credential
#   Oura:   Catherine & Sam / Personal Health Dashboard Oura API
#
# Optional overrides:
#   HEALTH_OP_WHOOP_VAULT, HEALTH_OP_WHOOP_ITEM
#   HEALTH_OP_STRAVA_VAULT, HEALTH_OP_STRAVA_ITEM
#   HEALTH_OP_OURA_VAULT, HEALTH_OP_OURA_ITEM

if ! command -v op >/dev/null 2>&1; then
  echo "1Password CLI 'op' is not installed or not on PATH." >&2
  return 1 2>/dev/null || exit 1
fi

export OP_ACCOUNT="${OP_ACCOUNT:-my.1password.com}"

_health_load_item() {
  local vault="$1"
  local item="$2"
  local keys="$3"

  OP_VAULT="$vault" OP_ITEM="$item" OP_KEYS="$keys" source scripts/load_op_env.sh
}

_health_load_item \
  "${HEALTH_OP_WHOOP_VAULT:-Catherine & Sam}" \
  "${HEALTH_OP_WHOOP_ITEM:-Personal Health Dashboard Whoop API}" \
  "WHOOP_CLIENT_ID WHOOP_CLIENT_SECRET WHOOP_REDIRECT_URI"

_health_load_item \
  "${HEALTH_OP_STRAVA_VAULT:-Private}" \
  "${HEALTH_OP_STRAVA_ITEM:-Strava API Credential}" \
  "STRAVA_CLIENT_ID STRAVA_CLIENT_SECRET STRAVA_REDIRECT_URI STRAVA_WEBHOOK_VERIFY_TOKEN STRAVA_WEBHOOK_SIGNING_SECRET"

_health_load_item \
  "${HEALTH_OP_OURA_VAULT:-Catherine & Sam}" \
  "${HEALTH_OP_OURA_ITEM:-Personal Health Dashboard Oura API}" \
  "OURA_CLIENT_ID OURA_CLIENT_SECRET OURA_REDIRECT_URI OURA_PERSONAL_ACCESS_TOKEN"
