# Automated Daily Health Check-In

This is the reusable prompt/runbook for a local health check-in. It refreshes connected provider APIs where possible, checks push-only Apple Health freshness, rebuilds daily features, and writes local report artifacts.

## Standard Command

Run from the repo root:

```bash
scripts/run_health_report_with_op_env.sh .venv/bin/python scripts/auto_health_report.py
```

Install the local provider refresh agent once to run the same credential-safe
sync every six hours with a seven-day overlap:

```bash
scripts/install_provider_refresh_agent.sh
```

The job retries naturally on its next interval if 1Password is unavailable.
Imports remain idempotent, and private reports/logs stay in the local ignored
directories. Remove only the schedule with
`scripts/uninstall_provider_refresh_agent.sh`; it does not delete health data.

Outputs are written to:

```text
local_exports/health_checkins/
```

The command does not print secrets or raw provider payloads. It writes both:

- `health_checkin_<date>.json`
- `health_checkin_<date>.md`

## What It Does

- Loads project API credentials from the current 1Password items:
  - WHOOP: `Catherine & Sam / Personal Health Dashboard Whoop API`
  - Strava: `Private / Strava API Credential`
  - Oura: `Catherine & Sam / Personal Health Dashboard Oura API`
- Runs WHOOP sync when a stored OAuth token exists.
- Runs Strava sync when a stored OAuth token exists.
- Runs Oura sync when a stored OAuth token exists, or when `OURA_PERSONAL_ACCESS_TOKEN` is loaded.
- Checks Apple Health freshness from local `raw_events` and `normalized_metrics`; Apple Health is push-only through Health Auto Export and cannot be pulled directly.
- Rebuilds `daily_features`.
- Reports facts, missing-data actions, and conservative suggestions.
- Includes extra normalized metrics already present in SQLite, without changing the schema.

Verify credential field presence without printing values:

```bash
scripts/check_health_op_env.sh
```

Oura app credentials are not enough by themselves. The local DB also needs an
Oura OAuth token from `/auth/oura/start`, unless a personal access token is
stored in `OURA_PERSONAL_ACCESS_TOKEN`.

## No API Sync Local Report

Use this when you only want to summarize already-uploaded data:

```bash
.venv/bin/python scripts/auto_health_report.py --no-sync
```

## Apple Health Staleness

If Apple Health is stale, first verify the receiver without importing probe rows:

```bash
scripts/check_health_auto_export_receiver.sh
```

If the receiver is not running and this checkout is still under `~/Documents`, start it manually from Terminal because macOS launchd can be blocked by privacy controls:

```bash
scripts/run_health_report_with_op_env.sh .venv/bin/python -m uvicorn health_dashboard.main:app --host 0.0.0.0 --port 8000
```

For an always-on LaunchAgent, move the repo to a non-protected path such as:

```text
~/Developer/personal-health-dashboard
```

Then install:

```bash
scripts/install_launch_agent.sh
```

Also install the Apple Health freshness monitor from the live checkout:

```bash
scripts/install_health_auto_export_monitor.sh
```

It runs hourly, checks that port `8000` is still owned by the expected checkout,
verifies the Health Auto Export receiver and shared secret, and warns if Apple
Health has not arrived within the configured freshness window.

## Agent Boundaries

- Treat the generated report as local context; it excludes raw payloads and secrets.
- Do not infer missing measurements.
- Do not provide medical diagnosis, medication dosing guidance, or treatment advice.
- Do not expose tokens, credential files, raw provider payloads, or local database contents.
- Keep Apple Health as fallback data; prefer direct provider records where the daily source flags indicate richer sources.
