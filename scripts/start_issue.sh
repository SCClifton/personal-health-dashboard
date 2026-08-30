#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <issue-number> [tool-name]" >&2
  exit 2
fi

ISSUE="$1"
TOOL="${2:-${PHD_TOOL:-codex}}"

for bin in git gh jq; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $bin" >&2
    exit 1
  fi
done

MAIN_WT=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')
if [[ -z "$MAIN_WT" ]]; then
  echo "ERROR: could not locate main worktree" >&2
  exit 1
fi

REPO=$(cd "$MAIN_WT" && gh repo view --json nameWithOwner -q '.nameWithOwner')
ME=$(gh api user -q '.login')

echo "==> Repo:          $REPO"
echo "==> Issue:         #$ISSUE"
echo "==> Tool:          $TOOL"
echo "==> Me:            $ME"
echo "==> Main worktree: $MAIN_WT"

echo
echo "==> Refreshing main"
(
  cd "$MAIN_WT"
  current=$(git branch --show-current)
  if [[ "$current" == "main" ]]; then
    git fetch --prune origin
    git pull --rebase
  else
    echo "    Main worktree is on '$current'; fetching only."
    git fetch --prune origin
  fi
)

echo
echo "==> Inspecting issue"
ISSUE_JSON=$(gh issue view "$ISSUE" --repo "$REPO" --json number,title,state,assignees)
STATE=$(echo "$ISSUE_JSON" | jq -r '.state')
TITLE=$(echo "$ISSUE_JSON" | jq -r '.title')
ASSIGNEES=$(echo "$ISSUE_JSON" | jq -r '.assignees[].login // empty' | tr '\n' ' ')

echo "    Title:     $TITLE"
echo "    State:     $STATE"
echo "    Assignees: ${ASSIGNEES:-<none>}"

if [[ "$STATE" != "OPEN" ]]; then
  echo "ERROR: issue #$ISSUE is $STATE; pick a different issue." >&2
  exit 1
fi

if [[ -n "$ASSIGNEES" && "$ASSIGNEES" != *"$ME"* ]]; then
  echo "ERROR: issue #$ISSUE is already assigned to $ASSIGNEES." >&2
  exit 1
fi

if [[ "$ASSIGNEES" != *"$ME"* ]]; then
  echo
  echo "==> Claiming issue"
  gh issue edit "$ISSUE" --repo "$REPO" --add-assignee "@me"
fi

SLUG=$(echo "$TITLE" \
  | tr '[:upper:]' '[:lower:]' \
  | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' \
  | cut -c1-40 \
  | sed -E 's/-+$//')
BRANCH="${TOOL}/${ISSUE}-${SLUG}"
WT_DIR="$(dirname "$MAIN_WT")/$(basename "$MAIN_WT")-${ISSUE}-${SLUG}"

echo
echo "==> Branch:   $BRANCH"
echo "==> Worktree: $WT_DIR"

if [[ -d "$WT_DIR" ]]; then
  echo "    Worktree already exists."
else
  if git -C "$MAIN_WT" show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git -C "$MAIN_WT" worktree add "$WT_DIR" "$BRANCH"
  else
    git -C "$MAIN_WT" worktree add "$WT_DIR" -b "$BRANCH" origin/main
  fi
fi

if [[ -f "$MAIN_WT/.env" && ! -e "$WT_DIR/.env" ]]; then
  ln -s "$MAIN_WT/.env" "$WT_DIR/.env"
  echo "    Linked .env"
fi

if [[ -d "$MAIN_WT/.venv" && ! -e "$WT_DIR/.venv" ]]; then
  case "${PHD_VENV:-symlink}" in
    own)
      echo "    Creating per-worktree .venv"
      (cd "$WT_DIR" && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt --quiet)
      ;;
    skip)
      echo "    PHD_VENV=skip; not creating .venv"
      ;;
    *)
      ln -s "$MAIN_WT/.venv" "$WT_DIR/.venv"
      echo "    Linked .venv"
      ;;
  esac
fi

cat <<EOF

==> Pre-flight complete.

cd into the worktree:
  cd "$WT_DIR"

Run tests:
  PYTHONPATH=src .venv/bin/python -m pytest -q

Open a draft PR after your first commit:
  gh pr create --draft --title "[#$ISSUE] $TITLE" --body "Closes #$ISSUE"

When the PR merges:
  scripts/finish_issue.sh $ISSUE
EOF
