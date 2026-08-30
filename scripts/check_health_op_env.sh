#!/usr/bin/env bash
set -euo pipefail

# Non-revealing check for the current Personal Health Dashboard 1Password items.

cd "$(dirname "$0")/.."

export OP_ACCOUNT="${OP_ACCOUNT:-my.1password.com}"

echo "WHOOP item: ${HEALTH_OP_WHOOP_VAULT:-Catherine & Sam} / ${HEALTH_OP_WHOOP_ITEM:-Personal Health Dashboard Whoop API}"
OP_VAULT="${HEALTH_OP_WHOOP_VAULT:-Catherine & Sam}" \
  OP_ITEM="${HEALTH_OP_WHOOP_ITEM:-Personal Health Dashboard Whoop API}" \
  scripts/check_op_env.sh WHOOP_CLIENT_ID WHOOP_CLIENT_SECRET WHOOP_REDIRECT_URI

echo
echo "Strava item: ${HEALTH_OP_STRAVA_VAULT:-Private} / ${HEALTH_OP_STRAVA_ITEM:-Strava API Credential}"
OP_VAULT="${HEALTH_OP_STRAVA_VAULT:-Private}" \
  OP_ITEM="${HEALTH_OP_STRAVA_ITEM:-Strava API Credential}" \
  scripts/check_op_env.sh STRAVA_CLIENT_ID STRAVA_CLIENT_SECRET STRAVA_REDIRECT_URI STRAVA_WEBHOOK_VERIFY_TOKEN

echo
echo "Oura item: ${HEALTH_OP_OURA_VAULT:-Catherine & Sam} / ${HEALTH_OP_OURA_ITEM:-Personal Health Dashboard Oura API}"
OP_VAULT="${HEALTH_OP_OURA_VAULT:-Catherine & Sam}" \
  OP_ITEM="${HEALTH_OP_OURA_ITEM:-Personal Health Dashboard Oura API}" \
  scripts/check_op_env.sh OURA_CLIENT_ID OURA_CLIENT_SECRET OURA_REDIRECT_URI

echo
echo "Optional Oura personal access token:"
item_json="$(op item get "${HEALTH_OP_OURA_ITEM:-Personal Health Dashboard Oura API}" --account "$OP_ACCOUNT" --vault "${HEALTH_OP_OURA_VAULT:-Catherine & Sam}" --format json)"
value="$(printf '%s' "$item_json" | jq -r '[.fields[]? | select(.label == "OURA_PERSONAL_ACCESS_TOKEN") | .value][0] // empty')"
if [[ -n "$value" ]]; then
  echo "OURA_PERSONAL_ACCESS_TOKEN=set"
else
  echo "OURA_PERSONAL_ACCESS_TOKEN=missing"
fi
