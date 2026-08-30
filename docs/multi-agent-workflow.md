# Multi-Agent Workflow

This repo uses GitHub issues, one worktree per issue, and draft PRs to keep human and AI work isolated.

## Rules

- The main worktree stays on `main` and is for reading/coordinating.
- Planned code changes happen in per-issue sibling worktrees.
- Every meaningful change starts from a GitHub issue.
- The issue assignee is the lock. If an issue is assigned to someone else, do not work it.
- AIs do not auto-merge PRs.
- Secret-bearing local files can be symlinked into worktrees, but never committed.

## Directory Pattern

```text
~/Documents/Projects/
├── personal-health-dashboard/
├── personal-health-dashboard-12-whoop-sync/
├── personal-health-dashboard-13-strava-webhooks/
└── personal-health-dashboard-14-dashboard-cleanup/
```

## Start Work

```bash
cd /Users/samuelclifton/Documents/Projects/personal-health-dashboard
scripts/start_issue.sh <issue-number> codex
cd ../personal-health-dashboard-<issue-number>-<slug>
```

The script:

1. Finds the canonical main worktree.
2. Fetches latest `origin/main`.
3. Verifies the GitHub issue is open.
4. Self-assigns the issue.
5. Creates `codex/<issue-number>-<slug>` from `origin/main`.
6. Creates a sibling worktree.
7. Symlinks `.env` and `.venv` when present.

## Work Loop

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
git status --short
git add <files>
git commit -m "feat(connector): add whoop sync job"
git push -u origin HEAD
gh pr create --draft --title "[#<issue>] <title>" --body "Closes #<issue>"
```

## Finish Work

After the PR merges:

```bash
cd /Users/samuelclifton/Documents/Projects/personal-health-dashboard
scripts/finish_issue.sh <issue-number>
```

## GitHub Project Board

If this repo is later attached to a GitHub Project, move cards manually for now:

- Backlog
- In Progress
- In Review
- Done

Do not edit GitHub Project configuration without explicit user approval.
