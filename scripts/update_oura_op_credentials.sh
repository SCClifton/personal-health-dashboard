#!/usr/bin/env bash
set -euo pipefail

# Update the project Oura API credentials in 1Password without echoing secrets.
#
# Usage:
#   scripts/update_oura_op_credentials.sh
#
# Optional:
#   OP_ACCOUNT="my.1password.com" OP_VAULT="Catherine & Sam" OP_ITEM="Personal Health Dashboard Oura API" scripts/update_oura_op_credentials.sh

if ! command -v op >/dev/null 2>&1; then
  echo "1Password CLI 'op' is not installed or not on PATH." >&2
  exit 1
fi

OP_ACCOUNT="${OP_ACCOUNT:-my.1password.com}"
OP_VAULT="${OP_VAULT:-Catherine & Sam}"
OP_ITEM="${OP_ITEM:-Personal Health Dashboard Oura API}"
OURA_REDIRECT_URI="${OURA_REDIRECT_URI:-http://localhost:8000/auth/oura/callback}"

OP_ARGS=(--account "$OP_ACCOUNT" --vault "$OP_VAULT")

if [[ -z "${OURA_CLIENT_ID:-}" ]]; then
  read -r -s -p "OURA_CLIENT_ID: " OURA_CLIENT_ID
  printf '\n'
fi

if [[ -z "${OURA_CLIENT_SECRET:-}" ]]; then
  read -r -s -p "OURA_CLIENT_SECRET: " OURA_CLIENT_SECRET
  printf '\n'
fi

read -r -p "OURA_REDIRECT_URI [$OURA_REDIRECT_URI]: " redirect_input
if [[ -n "$redirect_input" ]]; then
  OURA_REDIRECT_URI="$redirect_input"
fi

if [[ -z "$OURA_CLIENT_ID" || -z "$OURA_CLIENT_SECRET" || -z "$OURA_REDIRECT_URI" ]]; then
  echo "OURA_CLIENT_ID, OURA_CLIENT_SECRET, and OURA_REDIRECT_URI are required." >&2
  exit 1
fi

export OP_ITEM OURA_CLIENT_ID OURA_CLIENT_SECRET OURA_REDIRECT_URI

notes="Personal Health Dashboard Oura OAuth app credentials. Redirect URI must match the Oura developer app. Load with OP_ITEM=\"Personal Health Dashboard Oura API\" OP_KEYS=\"OURA_CLIENT_ID OURA_CLIENT_SECRET OURA_REDIRECT_URI\" source scripts/load_op_env.sh. Do not paste these values into chat or commit them to .env."

if op item get "$OP_ITEM" "${OP_ARGS[@]}" --format json >/dev/null 2>&1; then
  op item get "$OP_ITEM" "${OP_ARGS[@]}" --format json \
    | jq --arg notes "$notes" '
        .fields = (
          [.fields[]? | select((.label == "OURA_CLIENT_ID" or .label == "OURA_CLIENT_SECRET" or .label == "OURA_REDIRECT_URI" or .label == "notesPlain") | not)]
          + [
              {"id":"notesPlain","type":"STRING","purpose":"NOTES","label":"notesPlain","value":$notes},
              {"id":"oura_client_id","type":"STRING","label":"OURA_CLIENT_ID","value":env.OURA_CLIENT_ID},
              {"id":"oura_client_secret","type":"CONCEALED","label":"OURA_CLIENT_SECRET","value":env.OURA_CLIENT_SECRET},
              {"id":"oura_redirect_uri","type":"URL","label":"OURA_REDIRECT_URI","value":env.OURA_REDIRECT_URI}
            ]
        )
      ' \
    | op item edit "$OP_ITEM" "${OP_ARGS[@]}" >/dev/null
else
  op item template get "API Credential" --account "$OP_ACCOUNT" \
    | jq --arg notes "$notes" '
        .title = env.OP_ITEM
        | .fields = [
            {"id":"notesPlain","type":"STRING","purpose":"NOTES","label":"notesPlain","value":$notes},
            {"id":"oura_client_id","type":"STRING","label":"OURA_CLIENT_ID","value":env.OURA_CLIENT_ID},
            {"id":"oura_client_secret","type":"CONCEALED","label":"OURA_CLIENT_SECRET","value":env.OURA_CLIENT_SECRET},
            {"id":"oura_redirect_uri","type":"URL","label":"OURA_REDIRECT_URI","value":env.OURA_REDIRECT_URI}
          ]
      ' \
    | op item create "${OP_ARGS[@]}" --tags "personal-health-dashboard,oura" - >/dev/null
fi

unset OURA_CLIENT_ID OURA_CLIENT_SECRET OURA_REDIRECT_URI
echo "Updated Oura fields in 1Password item '$OP_ITEM' without printing secret values."
