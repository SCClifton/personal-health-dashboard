# Handoff Prompt - Unified Health Data Hub

Use this on 2026-05-31 to continue the Personal Health Dashboard work.

## Role

You are Codex working in `/Users/samuelclifton/Documents/Projects/personal-health-dashboard`. Build a local-first health coaching data hub that helps Sam track weight loss, blood pressure, sleep, nutrition, training, and biomarkers. Keep all health interpretation conservative and non-diagnostic.

## Current Health Context

Sam is approximately 116 kg at 186 cm. The current goal is to lose 15 kg over roughly three months while preserving lean mass and improving blood pressure, sleep, lipids, liver markers, and overall cardiometabolic risk.

Current evidence already extracted locally:

- EverLab review: `local_exports/everlab/processed/everlab_health_review_2026-05-30.md`
- EverLab SQLite: `local_exports/everlab/processed/everlab_results.sqlite`
- EverLab biomarker CSV: `local_exports/everlab/processed/everlab_biomarker_results.csv`
- EverLab body composition CSV: `local_exports/everlab/processed/everlab_body_composition_results.csv`
- Hilo BP review: `local_exports/hilo/processed/hilo_bp_review_2026-05-30.md`
- Hilo BP SQLite: `local_exports/hilo/processed/hilo_bp_2026-05.sqlite`
- Hilo BP readings CSV: `local_exports/hilo/processed/hilo_bp_readings_2026-05.csv`
- Coaching snapshot: `local_exports/coaching/coaching_snapshot_20260530T104748Z.md`
- Shared agent coaching rules: `docs/agent-coach-prompt.md`

Known clinical/coaching signals from the extracted data:

- Weight/body composition is the central modifiable lever.
- May 2026 Hilo BP is repeatedly high: Hilo report summary shows all-measurement mean 146/81, daytime/resting mean 150/84, night-time mean 140/76 across 1083 readings.
- Latest extracted EverLab labs from 2025-10-01 show HbA1c 5.2%, LDL-C 3.3 mmol/L, ApoB 0.92 g/L, ALT 67 U/L, AST 48 U/L, ferritin 382 ug/L, transferrin saturation 48%.
- Glucose/CGM data look reassuring in the extracted set, but weight, BP, LDL/ApoB, ALT/AST, and iron markers deserve monitoring and clinician discussion.
- 2023 DEXA extraction showed weight 113.8 kg, BMI 32.37, body fat 22.3%, lean 72.9%, VAT area 44.1 cm2.
- Latest 2025 DEXA/body scans are image-only and still need OCR/vision extraction.

## Boundaries

- Do not make medication, GLP-1 dose, or treatment recommendations.
- Do not scrape provider apps or reverse engineer app traffic.
- Do not transmit private health data or credentials to third parties without explicit permission.
- Preserve raw imports exactly and make normalization additive.
- Label Hilo as cuff-calibrated optical/wrist estimate data, useful for trend analysis but requiring clinician/cuff confirmation for medical decisions.
- For Eight Sleep, use official export/API/Apple Health routes only. If no official route is available, document the gap and use Apple Health summaries as fallback.

## Tomorrow's Engineering Objective

Unify the currently extracted and ongoing health data into one local data hub with source freshness, raw-event preservation, normalized metrics, and agent-readable snapshots.

Prioritise these data streams:

1. WHOOP official API for sleep, recovery, strain, workouts, and body measurements.
2. Apple Health via Health Auto Export for fallback health metrics, BP if Hilo sync is enabled, steps, workouts, HR, HRV, weight, and sleep summaries.
3. Hilo BP via Apple Health sync, Hilo CSV support export, or monthly/weekly PDF parser.
4. MyFitnessPal Premium export for nutrition, calories, macros, weight/progress, and exercise.
5. EverLab reports as read-only biomarker/body-composition source.
6. Eight Sleep via official export/API if available; otherwise Apple Health sleep/temperature summaries only.
7. HYBRD only through official export/API sample; otherwise use Strava/Garmin/Apple Health workout summaries.

## First Actions

1. Read `AGENTS.md`, `README.md`, `docs/credential-management.md`, `docs/health-auto-export-automation.md`, and `docs/agent-coach-prompt.md`.
2. Inspect current schema and ingestion services:
   - `src/health_dashboard/models.py`
   - `src/health_dashboard/schema.sql`
   - `src/health_dashboard/services/ingestion.py`
   - `src/health_dashboard/services/normalization.py`
   - `src/health_dashboard/connectors/status.py`
3. Check existing connector code for WHOOP, Apple Health, CSV imports, and any Eight Sleep placeholders.
4. Run the current tests:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

5. Check source freshness and dashboard state against the local SQLite DB before changing schema.

## Implementation Plan

### A. WHOOP API

- Use official WHOOP OAuth/API only.
- Confirm scopes in `.env.example` and `docs/credential-management.md`.
- Use project-approved 1Password loading scripts without printing secrets.
- Implement or finish a sync script that pulls sleep, recovery, cycles, workouts, profile, and body measurements into `raw_events`.
- Add normalization into source-aware metrics and daily features.
- Add tests with fixtures, not live API credentials.

### B. Health Auto Export

- Verify the existing Apple Health ingest endpoint and shared-secret flow.
- Ensure BP, weight, steps, workouts, sleep, HR, HRV, resting HR, active energy, and dietary fields are mapped where available.
- Document exact iPhone Health Auto Export settings Sam should enable.
- Treat Apple Health as fallback data where richer provider data exists.

### C. Hilo BP

- Add a local Hilo PDF/CSV importer if not already implemented as first-class code.
- Store raw report metadata and individual readings.
- Normalize systolic BP, diastolic BP, and HR with source `hilo`.
- Add daily, daytime, night-time summaries and source freshness warnings.
- Include a dashboard panel that highlights BP trends without diagnosing.

### D. EverLab

- Bring extracted EverLab SQLite/CSV into the dashboard as a read-only biomarker source.
- Preserve raw PDFs and extracted rows.
- Add canonical biomarker mapping for equivalent names.
- Prioritise OCR/vision extraction for the 2025 DEXA/body-measurement scans.

### E. Eight Sleep

- Research official current export/API/Apple Health support before coding.
- If official export/API exists, add connector status and ingestion plan.
- If not, document fallback: Apple Health sleep summaries, temperature if available, and manual monthly exports if EverLab or Eight Sleep supports them.
- Do not scrape the app or use account credentials outside official flows.

### F. Coaching Snapshot

- Update `scripts/export_coaching_snapshot.py` so it includes:
  - source freshness by provider,
  - weight trend,
  - BP trend and Hilo freshness,
  - sleep/recovery trend from WHOOP/Apple Health,
  - nutrition adherence from MyFitnessPal,
  - training adherence from Strava/HYBRD fallback/Apple Health,
  - biomarker watchlist from EverLab,
  - missing-data checklist,
  - conservative agent instructions.

## Acceptance Criteria

- `PYTHONPATH=src .venv/bin/python -m pytest -q` passes.
- Raw provider data remains preserved in `raw_events` or local raw export folders.
- No secrets are printed, committed, or written to tracked files.
- `/dashboard/coach` and `/dashboard/data-quality` show BP and biomarker gaps/source freshness clearly.
- Agent snapshot can be generated locally and read by Claude, Cursor, or Codex without live credentials.
- Any unsupported provider path is documented as blocked/fallback, not hacked around.

## Suggested First Question For Sam

Ask Sam to confirm which data routes are already enabled on his phone:

- Hilo -> Apple Health blood pressure sync.
- Health Auto Export schedule and endpoint.
- WHOOP developer app/OAuth status.
- MyFitnessPal Premium export cadence.
- Eight Sleep Apple Health sync/export availability.

Do not ask for passwords. If credentials are needed, use the repo's 1Password workflow and only after Sam confirms.
