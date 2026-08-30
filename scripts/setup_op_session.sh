#!/usr/bin/env bash
set -euo pipefail

# Source this once per terminal session to set the repo's default 1Password context.
#
# Usage:
#   source scripts/setup_op_session.sh
#
# Optional overrides:
#   OP_VAULT="Other Vault" OP_ITEM="Other Item" source scripts/setup_op_session.sh
#   OP_ACCOUNT="my.1password.com" OP_VAULT="Catherine & Sam" source scripts/setup_op_session.sh

if ! command -v op >/dev/null 2>&1; then
  echo "1Password CLI 'op' is not installed or not on PATH." >&2
  return 1 2>/dev/null || exit 1
fi

export OP_VAULT="${OP_VAULT:-Catherine & Sam}"
export OP_ITEM="${OP_ITEM:-Personal Health Dashboard Whoop API}"
export OP_KEYS="${OP_KEYS:-WHOOP_CLIENT_ID WHOOP_CLIENT_SECRET WHOOP_REDIRECT_URI}"

account_args=()
if [[ -n "${OP_ACCOUNT:-}" ]]; then
  account_args+=(--account "$OP_ACCOUNT")
fi

if ! op whoami "${account_args[@]}" >/dev/null 2>&1; then
  if [[ -n "${OP_ACCOUNT:-}" ]]; then
    echo "1Password CLI is not signed in for ${OP_ACCOUNT}. Run: op signin --account ${OP_ACCOUNT}" >&2
  else
    echo "1Password CLI is not signed in. Run: op signin" >&2
  fi
  return 1 2>/dev/null || exit 1
fi

scripts/check_op_env.sh ${OP_KEYS}

echo "1Password session context set for OP_ACCOUNT, OP_VAULT, OP_ITEM, and OP_KEYS."
