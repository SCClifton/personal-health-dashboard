#!/usr/bin/env bash
set -euo pipefail

# Copy the current Oura OAuth token pair from the local dashboard database into
# a dedicated 1Password API Credential item without printing either secret.
#
# The database remains the runtime source because Oura may rotate tokens during
# refresh. Run this command again after a new OAuth authorisation when a current
# recovery snapshot is needed.

if ! command -v op >/dev/null 2>&1; then
  echo "1Password CLI 'op' is not installed or not on PATH." >&2
  exit 1
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 is not installed or not on PATH." >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is not installed or not on PATH." >&2
  exit 1
fi

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
db_path="${HEALTH_DB_PATH:-${project_dir}/data/health_dashboard.db}"
op_account="${OP_ACCOUNT:-my.1password.com}"
op_vault="${OP_VAULT:-Catherine & Sam}"
op_item="${OP_ITEM:-Personal Health Dashboard Oura OAuth Token}"

if [[ ! -f "$db_path" ]]; then
  echo "Health database not found: $db_path" >&2
  exit 1
fi

umask 077
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
token_json="${tmp_dir}/token.json"
item_json="${tmp_dir}/item.json"

sqlite3 -json "$db_path" \
  "SELECT access_token, refresh_token, token_type, scope, expires_at, updated_at
   FROM oauth_tokens WHERE provider = 'oura' LIMIT 1;" >"$token_json"

if ! jq -e 'length == 1 and .[0].access_token != null and .[0].refresh_token != null' "$token_json" >/dev/null; then
  echo "No complete Oura OAuth token pair is stored in the health database." >&2
  exit 1
fi

notes="Recovery snapshot of the Personal Health Dashboard Oura OAuth credential. The local SQLite database is the runtime source of truth because Oura may rotate tokens during refresh. Re-run scripts/backup_oura_oauth_token_to_op.sh after reauthorising Oura. Created without printing secret values."
op_args=(--account "$op_account" --vault "$op_vault")

if op item get "$op_item" "${op_args[@]}" --format json >"$item_json" 2>/dev/null; then
  jq --slurpfile token "$token_json" --arg notes "$notes" '
    .fields = (
      [.fields[]? | select(
        (.label == "notesPlain" or .label == "username" or .label == "credential" or
         .label == "refresh_token" or .label == "token_type" or .label == "scope" or
         .label == "expires_at" or .label == "database_record" or .label == "hostname") | not
      )]
      + [
          {"id":"notesPlain","type":"STRING","purpose":"NOTES","label":"notesPlain","value":$notes},
          {"id":"username","type":"STRING","label":"username","value":"oura"},
          {"id":"credential","type":"CONCEALED","label":"credential","value":$token[0][0].access_token},
          {"id":"refresh_token","type":"CONCEALED","label":"refresh_token","value":$token[0][0].refresh_token},
          {"id":"token_type","type":"STRING","label":"token_type","value":($token[0][0].token_type // "bearer")},
          {"id":"scope","type":"STRING","label":"scope","value":($token[0][0].scope // "")},
          {"id":"expires_at","type":"STRING","label":"expires_at","value":($token[0][0].expires_at // "")},
          {"id":"database_record","type":"STRING","label":"database_record","value":"oauth_tokens/provider=oura"},
          {"id":"hostname","type":"STRING","label":"hostname","value":"api.ouraring.com"}
        ]
    )
  ' "$item_json" >"${tmp_dir}/updated-item.json"
  op item edit "$op_item" "${op_args[@]}" --template "${tmp_dir}/updated-item.json" \
    --tags "personal-health-dashboard,oura,oauth,recovery-snapshot" >/dev/null
  action="Updated"
else
  op item template get "API Credential" --account "$op_account" --format json \
    | jq --slurpfile token "$token_json" --arg title "$op_item" --arg notes "$notes" '
        .title = $title
        | .fields = [
            {"id":"notesPlain","type":"STRING","purpose":"NOTES","label":"notesPlain","value":$notes},
            {"id":"username","type":"STRING","label":"username","value":"oura"},
            {"id":"credential","type":"CONCEALED","label":"credential","value":$token[0][0].access_token},
            {"id":"refresh_token","type":"CONCEALED","label":"refresh_token","value":$token[0][0].refresh_token},
            {"id":"token_type","type":"STRING","label":"token_type","value":($token[0][0].token_type // "bearer")},
            {"id":"scope","type":"STRING","label":"scope","value":($token[0][0].scope // "")},
            {"id":"expires_at","type":"STRING","label":"expires_at","value":($token[0][0].expires_at // "")},
            {"id":"database_record","type":"STRING","label":"database_record","value":"oauth_tokens/provider=oura"},
            {"id":"hostname","type":"STRING","label":"hostname","value":"api.ouraring.com"}
          ]
      ' >"${tmp_dir}/new-item.json"
  op item create "${op_args[@]}" --tags "personal-health-dashboard,oura,oauth,recovery-snapshot" \
    --template "${tmp_dir}/new-item.json" >/dev/null
  action="Created"
fi

echo "${action} 1Password item '${op_item}' in vault '${op_vault}' without printing secret values."
