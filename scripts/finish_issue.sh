#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <issue-number> [--force]" >&2
  exit 2
fi

ISSUE="$1"

MAIN_WT=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')
if [[ -z "$MAIN_WT" ]]; then
  echo "ERROR: could not locate main worktree" >&2
  exit 1
fi

WT_LINE=$(git -C "$MAIN_WT" worktree list --porcelain | grep -B2 "branch refs/heads/.*${ISSUE}-" | grep "^worktree " | head -1 || true)
WT_DIR="${WT_LINE#worktree }"

if [[ -z "$WT_DIR" ]]; then
  echo "No worktree found for issue #$ISSUE. Nothing to clean up."
  exit 0
fi

BRANCH_LINE=$(git -C "$MAIN_WT" worktree list --porcelain | grep -A2 "^worktree $WT_DIR$" | grep "^branch " | head -1)
BRANCH="${BRANCH_LINE#branch refs/heads/}"

echo "==> Worktree: $WT_DIR"
echo "==> Branch:   $BRANCH"

if ! git -C "$MAIN_WT" branch --merged origin/main | grep -q "^[ *]\+$BRANCH$"; then
  echo "WARNING: branch $BRANCH is not merged into origin/main."
  if [[ "${2:-}" != "--force" ]]; then
    echo "Aborting. Re-run with --force to delete anyway."
    exit 1
  fi
fi

git -C "$MAIN_WT" worktree remove "$WT_DIR"
git -C "$MAIN_WT" branch -D "$BRANCH" 2>/dev/null || true
git -C "$MAIN_WT" worktree prune

echo "==> Cleaned up issue #$ISSUE."
