#!/usr/bin/env bash
set -euo pipefail

# Update the project WHOOP API credentials in 1Password without echoing secrets.
#
# Usage:
#   scripts/update_whoop_op_credentials.sh
#
# Optional:
#   OP_VAULT="Catherine & Sam" OP_ITEM="Personal Health Dashboard Whoop API" scripts/update_whoop_op_credentials.sh

if ! command -v op >/dev/null 2>&1; then
  echo "1Password CLI 'op' is not installed or not on PATH." >&2
  exit 1
fi

OP_VAULT="${OP_VAULT:-Catherine & Sam}"
OP_ITEM="${OP_ITEM:-Personal Health Dashboard Whoop API}"
WHOOP_REDIRECT_URI="${WHOOP_REDIRECT_URI:-http://localhost:8000/auth/whoop/callback}"

if [[ -z "${WHOOP_CLIENT_ID:-}" ]]; then
  read -r -p "WHOOP_CLIENT_ID: " WHOOP_CLIENT_ID
fi

if [[ -z "${WHOOP_CLIENT_SECRET:-}" ]]; then
  read -r -s -p "WHOOP_CLIENT_SECRET: " WHOOP_CLIENT_SECRET
  printf '\n'
fi

if [[ -z "$WHOOP_CLIENT_ID" || -z "$WHOOP_CLIENT_SECRET" ]]; then
  echo "WHOOP_CLIENT_ID and WHOOP_CLIENT_SECRET are required." >&2
  exit 1
fi

export WHOOP_CLIENT_ID WHOOP_CLIENT_SECRET WHOOP_REDIRECT_URI
op item get "$OP_ITEM" --vault "$OP_VAULT" --format json \
  | jq '
      .fields = (
        [.fields[] | select((.label == "WHOOP_CLIENT_ID" or .label == "WHOOP_CLIENT_SECRET" or .label == "WHOOP_REDIRECT_URI") | not)]
        + [
            {"id":"whoop_client_id","type":"STRING","label":"WHOOP_CLIENT_ID","value":env.WHOOP_CLIENT_ID},
            {"id":"whoop_client_secret","type":"CONCEALED","label":"WHOOP_CLIENT_SECRET","value":env.WHOOP_CLIENT_SECRET},
            {"id":"whoop_redirect_uri","type":"URL","label":"WHOOP_REDIRECT_URI","value":env.WHOOP_REDIRECT_URI}
          ]
      )
    ' \
  | op item edit "$OP_ITEM" --vault "$OP_VAULT" >/dev/null

unset WHOOP_CLIENT_ID WHOOP_CLIENT_SECRET WHOOP_REDIRECT_URI
echo "Updated WHOOP fields in 1Password item '$OP_ITEM' without printing secret values."
