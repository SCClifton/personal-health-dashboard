# AGENTS.md

Operating manual for any human or AI agent working in this repo. Read this before writing code.

**Last updated:** 2026-05-03

## 1. What This Project Is

A private, local-first personal health data platform. It ingests direct provider APIs where official APIs exist, uses Apple Health through Health Auto Export as the broad fallback, preserves raw payloads, normalizes canonical metrics, and exposes dashboards for GLP-1 response, sleep/recovery, blood pressure, weight/nutrition, and training.

- **Backend:** FastAPI under `src/health_dashboard/`.
- **Storage:** SQLite by default for local development; PostgreSQL through Docker Compose.
- **Dashboard:** Server-rendered local HTML pages for fast iteration.
- **Ingestion:** Adapter-based connectors plus raw event preservation.
- **Privacy posture:** Local/private by default. No password-based scraping.

## 2. Sources Of Truth

| Question | File |
|---|---|
| How do I run it? | `README.md` |
| What env vars exist? | `.env.example` |
| What is the schema? | `src/health_dashboard/models.py` and `src/health_dashboard/schema.sql` |
| How are source priorities applied? | `src/health_dashboard/services/normalization.py` |
| How is ingestion stored? | `src/health_dashboard/services/ingestion.py` |
| How do connectors report status? | `src/health_dashboard/connectors/status.py` |
| How do multiple agents coordinate? | `docs/multi-agent-workflow.md` |
| How are secrets handled? | `docs/credential-management.md` |

If two sources disagree, fix the disagreement in the same change.

## 3. Non-Negotiables

1. **Never commit secrets.** `.env`, local databases, exports, and API credentials stay out of Git.
2. **Use 1Password CLI only with guardrails.** Sam authorizes agents to use `op` for this project to read, create, and update project-specific API credential items and to load secrets into local commands. Do not print secret values, paste them into chat, commit them, or transmit them anywhere except the explicitly intended local process or approved provider API/OAuth flow.
3. **No password-based scraping.** Use official APIs, Health Auto Export, or user-provided exports only.
4. **Preserve raw payloads exactly.** Raw source records go into `raw_events`; normalization is additive.
5. **Apple Health is fallback data.** It fills gaps but must not silently overwrite richer direct-source records.
6. **Keep sources separated.** WHOOP, Oura, Garmin, Eight Sleep, Apple Watch, and Apple Health sleep/workout records should remain distinguishable.
7. **Correlations are exploratory, not diagnostic.** User-facing copy must not imply medical advice.
8. **Stable idempotency.** Imports must deduplicate by provider/source ID or payload hash.
9. **Official docs first.** Before implementing or changing an API connector, verify current official/public docs.
10. **Tests cover ingestion risk.** Add or update tests for duplicate imports, unit normalization, timezone handling, source priority, and missing-integration dashboard renders.

## 4. Stop And Ask Before

- Adding any unofficial connector or scraping login-protected pages.
- Transmitting health data, contact info, API secrets, tokens, or local files to a third party.
- Using 1Password, browser password managers, or credential vaults outside the project-specific items and fields described in `.env.example` or `docs/credential-management.md`.
- Revealing, exporting, copying, or writing secrets to disk in plaintext except when Sam explicitly asks for a local `.env` update.
- Logging into a third-party website or provider dashboard with credentials from 1Password.
- Deleting local data, exports, databases, or cloud resources.
- Creating OAuth/API credentials in a provider dashboard.
- Editing GitHub repo settings, branch protection, secrets, Actions variables, or Project configuration.
- Making medical, dosing, or treatment recommendations.
- Force-pushing, rewriting `main`, or deleting branches with unmerged work.

## 5. Repo Conventions

### Code

- Python package code lives under `src/health_dashboard/`.
- Keep connector-specific API logic under `src/health_dashboard/connectors/`.
- Keep normalization/source-priority rules under `src/health_dashboard/services/`.
- Keep tests fixture-driven and local. Do not require live provider credentials for standard test runs.
- Prefer explicit, typed functions for import/normalization logic.

### Secrets

- `.env.example` is committed. `.env` is not.
- Use 1Password field labels that exactly match `.env.example`.
- The default item name is `Personal Health Dashboard`; if using another item name, set `OP_ITEM`.
- Agents may run `op` commands for project-specific items, including field-presence checks, reading values into environment variables, and creating/updating fields that match `.env.example`.
- When using `op`, keep command output non-revealing. Do not run commands that print raw secret values to the terminal or chat.
- Prefer process-scoped loading with `scripts/run_with_op_env.sh` for app/server commands. Write `.env` only when Sam explicitly requests persistent local config.
- For repeated commands, source `scripts/setup_op_session.sh` once per terminal session to set `OP_VAULT`, `OP_ITEM`, and `OP_KEYS`.
- For WHOOP credential updates, prefer `scripts/update_whoop_op_credentials.sh` so the secret is read silently instead of being passed as a command argument.
- For daily health reviews, prefer `scripts/run_health_report_with_op_env.sh` or source `scripts/load_health_op_env.sh`; the current provider items are:
  - WHOOP: `Catherine & Sam / Personal Health Dashboard Whoop API`
  - Strava: `Private / Strava API Credential`
  - Oura: `Catherine & Sam / Personal Health Dashboard Oura API`
- Check those items without printing values via `scripts/check_health_op_env.sh`.
- Oura app credentials alone do not mean direct Oura data is available. Direct Oura sync requires a stored `oauth_tokens` row from `/auth/oura/start` or a loaded `OURA_PERSONAL_ACCESS_TOKEN`.
- Run:

```bash
OP_ITEM="Personal Health Dashboard Whoop API" source scripts/load_op_env.sh
```

or merge the WHOOP fields into a single item named `Personal Health Dashboard`.

### Branching

- Do not commit directly on `main` for planned work.
- Use one GitHub issue per meaningful change.
- Use `scripts/start_issue.sh <issue-number> codex` to create a per-issue worktree.
- Branch format: `codex/<issue-number>-<slug>`.
- Worktree format: `../personal-health-dashboard-<issue-number>-<slug>/`.

### Commits

- One concern per commit.
- Conventional Commits format: `<type>(<scope>): <subject>`.
- Run tests or document why they were not run.
- Do not add AI-tool attribution trailers.

## 6. Common Commands

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
scripts/run_health_report_with_op_env.sh .venv/bin/python scripts/auto_health_report.py
PYTHONPATH=src .venv/bin/python -m uvicorn health_dashboard.main:app --host 0.0.0.0 --port 8000
docker compose up --build
```

Load 1Password-backed environment variables after the user has created/saved the vault item:

```bash
eval "$(op signin)"
OP_ITEM="Personal Health Dashboard Whoop API" source scripts/load_op_env.sh
```

Verify connector status:

```bash
curl -s http://127.0.0.1:8000/api/connectors
```

## 7. Connector Notes

- **Apple Health:** Health Auto Export posts to `/ingest/apple-health` with shared-secret auth.
- **WHOOP:** OAuth app needs `offline read:recovery read:cycles read:workout read:sleep read:profile read:body_measurement`. The current app was created with all listed read scopes; confirm `offline` is requested in the OAuth authorization URL.
- **Strava:** Official OAuth API. Webhooks require public HTTPS.
- **Oura:** OAuth or personal access token.
- **Garmin:** Approval-gated Health API.
- **Eight Sleep:** Fallback-only unless official API access is available.
- **Nutrition:** MyFitnessPal Premium export CSV/zip first. No password scraping.

## 8. Tone

Be direct and practical. Read the code, make the change, run the relevant tests, and report the result. Keep health claims conservative and source-aware.
