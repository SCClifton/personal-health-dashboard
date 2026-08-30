# Personal Health Dashboard

Local-first personal health data platform for private ingestion, normalization, and dashboarding.

The app stores raw source payloads and normalized canonical metrics separately. Apple Health via Health Auto Export is treated as a broad fallback and does not overwrite richer direct-source records such as validated cuff BP, Strava/Garmin workouts, WHOOP/Oura sleep, or direct scale data.

## Project Management

- Delivery work is organised through one GitHub issue and one issue branch/worktree per meaningful change.
- The generic delivery sequence and source model live in `docs/delivery-roadmap.md`.
- Personal measurements, goal values, routes, raw exports, credentials, databases, logs, and generated reports stay local and are excluded from Git.
- Pull requests use the repository privacy checklist and must pass the fixture-driven test workflow.

## Current Scope

- FastAPI app with local dashboard pages.
- SQLite by default for quick local use; Docker Compose runs PostgreSQL.
- Raw event, normalized metric, and daily feature tables.
- Health Auto Export ingestion endpoint with shared-secret auth.
- OAuth scaffolding for WHOOP, Strava, and Oura.
- Garmin status scaffold marked approval-gated.
- Eight Sleep status scaffold marked fallback-only.
- Manual/CSV import adapters for BP, weight, and nutrition, including MyFitnessPal zip/CSV exports.
- First-class tirzepatide dose logging.
- Goal-aware coaching dashboard for weight-loss progress, nutrition adherence, training/sleep context, and missing-data actions.
- Read-only coaching snapshot exports for Claude, Cursor, and Codex.
- Connector status page at `/connectors`.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
PYTHONPATH=src uvicorn health_dashboard.main:app --reload
```

Open http://localhost:8000.

The coaching dashboard is available at:

```text
http://localhost:8000/dashboard/coach
```

For PostgreSQL:

```bash
cp .env.example .env
docker compose up --build
```

## Local Database Operations

SQLite is the default local database and is suitable for the private single-user
dashboard. File-backed SQLite connections run with WAL mode, foreign-key checks,
and a busy timeout so the receiver, dashboards, and reports can coexist more
reliably.

Create a checked compressed backup without stopping the dashboard:

```bash
.venv/bin/python scripts/backup_health_db.py
```

Install a daily local backup LaunchAgent:

```bash
scripts/install_db_backup_agent.sh
```

Backups are written under `local_exports/db_backups/`, which is intentionally
not committed. Use PostgreSQL through Docker Compose only when you need a
separate database service, heavier concurrent writes, or external SQL tooling.

## 1Password CLI Secret Loading

Do not commit `.env` or API secrets. To load fields from a 1Password item whose field labels match `.env.example`:

```bash
eval "$(op signin)"
OP_ITEM="Personal Health Dashboard" source scripts/load_op_env.sh
PYTHONPATH=src uvicorn health_dashboard.main:app --reload
```

For a WHOOP-only item, first verify the required fields without printing values:

```bash
eval "$(op signin)"
OP_VAULT="Catherine & Sam" OP_ITEM="Personal Health Dashboard Whoop API" scripts/check_op_env.sh
```

For repeated work in the same terminal session, set the repo's 1Password context once:

```bash
source scripts/setup_op_session.sh
```

Then run the app with the WHOOP credentials loaded only into the server process:

```bash
scripts/run_with_op_env.sh
```

If the item is in a specific vault, include `OP_VAULT="Vault Name"` in either command.

For daily health reports and provider refreshes, use the health-specific loader
instead. It loads the current provider items without printing values:

```bash
scripts/check_health_op_env.sh
scripts/run_health_report_with_op_env.sh .venv/bin/python scripts/auto_health_report.py
```

Current project item locations:

```text
WHOOP:  Catherine & Sam / Personal Health Dashboard Whoop API
Strava: Private / Strava API Credential
Oura:   Catherine & Sam / Personal Health Dashboard Oura API
```

Oura client credentials only configure the app. Direct Oura data still requires
local OAuth authorization at `/auth/oura/start`, unless
`OURA_PERSONAL_ACCESS_TOKEN` is present in the Oura item.

## Apple Health / Health Auto Export

Set `HEALTH_AUTO_EXPORT_SHARED_SECRET` and configure Health Auto Export REST API automation to POST JSON to:

```text
http://localhost:8000/ingest/apple-health
```

The automatic receiver is home-only. Prefer the Mac's Bonjour hostname so the
iPhone automation follows its current DHCP address:

```text
http://SamCliftons-MacBook-Pro.local:8000/ingest/apple-health
```

Keep macOS Wi-Fi and DNS on DHCP/automatic. The LaunchAgent identifies home by
the configured gateway address plus router MAC address; the Mac itself does not
need a fixed address. On public Wi-Fi, hotspots, or no Wi-Fi it binds to
`127.0.0.1` and Health Auto Export catches up after returning home.

To keep the receiver running automatically at login:

```bash
scripts/install_launch_agent.sh
scripts/check_health_auto_export_receiver.sh
```

See `docs/health-auto-export-automation.md` for the full Mac + iPhone automation
flow, eero reservation steps, and public-network verification.

Send the shared secret as either:

- `Authorization: Bearer <secret>`
- `X-Health-Auto-Export-Secret: <secret>`

The endpoint supports bulk arrays and incremental single-record uploads.

## OAuth Connectors

WHOOP: create an app in the WHOOP Developer Dashboard, set the redirect URL, and request `offline read:recovery read:cycles read:workout read:sleep read:profile read:body_measurement`. Start auth at `/auth/whoop/start`, then ingest the last 30 days with:

```bash
curl -X POST 'http://127.0.0.1:8000/sync/whoop?days=30'
```

To update the WHOOP API credential fields in 1Password without echoing secrets:

```bash
scripts/update_whoop_op_credentials.sh
```

Strava: create/manage a Strava app, set redirect URL, and start auth at `/auth/strava/start`. Webhook verification is scaffolded at `/webhooks/strava`. The current API credential item is `Private / Strava API Credential`; daily report commands should use `scripts/run_health_report_with_op_env.sh` so token refreshes have `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` loaded.

Oura: create an Oura API app, set the redirect URL to `http://localhost:8000/auth/oura/callback`, set `OURA_CLIENT_ID` and `OURA_CLIENT_SECRET`, then start auth at `/auth/oura/start`. OAuth is the primary path; `OURA_PERSONAL_ACCESS_TOKEN` is a legacy/local fallback. After authorization, ingest recent Oura data with:

```bash
curl -X POST 'http://127.0.0.1:8000/sync/oura?days=30'
```

To update the Oura API credential fields in 1Password without echoing secrets:

```bash
OP_ACCOUNT="my.1password.com" OP_VAULT="Catherine & Sam" OP_ITEM="Personal Health Dashboard Oura API" scripts/update_oura_op_credentials.sh
```

Garmin: official Health API access is approval-gated; use Apple Health, Strava, or file imports until approved.

Eight Sleep: no official stable public developer API is configured here; use Apple Health fallback. Password scraping is intentionally excluded.

## Imports

Upload local CSV or zip files:

```bash
curl -F "file=@data/myfitnesspal-export.zip" -F "source=myfitnesspal" http://localhost:8000/imports/nutrition
curl -F "file=@bp.csv" -F "source=manual_cuff" http://localhost:8000/imports/bp
curl -F "file=@weight.csv" -F "source=manual" http://localhost:8000/imports/weight
```

Expected CSV columns can include `observed_at_local`, `date`, `weight`, `weight (lbs)`, `calories`, `protein`, `carbs`, `fat`, `systolic`, and `diastolic`.

MyFitnessPal Premium exports are treated as the canonical nutrition import. The importer also recognizes common export headers such as `Protein (g)`, `Carbohydrates (g)`, `Fat (g)`, `Weight (lbs)`, `Exercise`, and `Exercise Calories`.

Hilo BP exports should use `observed_at_local`, `systolic_bp`, and `diastolic_bp` when available. Manual cuff readings remain the highest-priority BP source, Hilo is the cuff-calibrated longitudinal source, and Apple Health BP remains fallback.

Generate a local HRV/sleep source-concordance report with:

```bash
PYTHONPATH=src .venv/bin/python scripts/source_concordance_report.py --days 90
```

HYBRD is tracked as official-export/API required. Do not scrape HYBRD or reverse engineer app traffic; use Strava/Garmin/Apple Health summaries until HYBRD provides an official data path.

## Run Recovery Analysis

Routine Strava sync stays summary-only so regular reports do not burn stream API quota:

```bash
curl -X POST 'http://127.0.0.1:8000/sync/strava?days=30'
```

For repeat-level run analysis, use the rich run sync after the activity has landed in Strava:

```bash
curl -X POST 'http://127.0.0.1:8000/sync/strava/runs?days=7'
curl -X POST 'http://127.0.0.1:8000/sync/strava/runs?activity_id=STRAVA_ACTIVITY_ID'
```

The rich sync stores Strava summary, activity detail, laps, and streams as separate local `raw_events` records. The run dashboard is available at:

```text
http://localhost:8000/dashboard/runs
```

Useful JSON endpoints:

```bash
curl -s 'http://127.0.0.1:8000/api/runs/recent?days=14'
curl -s 'http://127.0.0.1:8000/api/runs/STRAVA_ACTIVITY_ID/recovery'
```

The recovery view detects 350-450 m work laps, reports each repeat's pace and heart-rate recovery during the following rest window, and labels confidence when laps or HR streams are missing. Private Strava activities may require re-authorizing with `activity:read_all`.

Garmin remains approval-gated for direct API access. If Strava does not preserve enough workout structure, the fallback path is a local user-provided Garmin FIT export/import workflow: keep the file local, preserve the raw file-derived payload, and do not scrape Garmin Connect or use password-based automation.

Log tirzepatide:

```bash
curl -X POST http://localhost:8000/medication/tirzepatide \
  -H 'Content-Type: application/json' \
  -d '{"dose_mg": 5, "taken_at": "2026-05-03T08:00:00+10:00", "appetite": "lower", "notes": "weekly dose"}'
```

Record clinician/source-backed dose-change context separately from actual doses:

```bash
curl -X POST http://localhost:8000/medication/tirzepatide/dose-context \
  -H 'Content-Type: application/json' \
  -d '{"prior_dose_mg": 2.5, "planned_dose_mg": 5, "planned_start_date": "2026-06-19", "clinician_name": "Vanessa Alimin", "source_type": "transcript"}'
```

The GLP-1 dashboard at `/dashboard/glp1` shows the latest planned context alongside weight, nutrition, blood pressure, recovery, sleep, and training markers. Planned context is not treated as an administered dose.

## Tests

```bash
PYTHONPATH=src pytest
```

## Coaching Snapshots

Generate a local read-only snapshot pack for Claude, Cursor, or Codex:

```bash
PYTHONPATH=src .venv/bin/python scripts/export_coaching_snapshot.py --days 90
```

Outputs are written under `local_exports/coaching/`, which is gitignored. See `docs/agent-coach-prompt.md` for the shared agent prompt and privacy boundaries.

## API Documentation Checked

Implementation details were checked against current official/public documentation:

- WHOOP OAuth 2.0: https://developer.whoop.com/docs/developing/oauth/
- WHOOP API scopes/endpoints: https://developer.whoop.com/api/
- Strava API: https://developers.strava.com/
- Strava Webhooks: https://developers.strava.com/docs/webhooks/
- Oura API: https://cloud.ouraring.com/docs/
- Garmin Health API: https://developer.garmin.com/gc-developer-program/health-api/
- MyFitnessPal Export: https://support.myfitnesspal.com/hc/en-us/articles/360032273352-Data-Export-FAQs
- Health Auto Export REST API: https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/

Correlation pages are exploratory only and are not diagnostic.
