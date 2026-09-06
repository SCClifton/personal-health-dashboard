---
name: log-98-workout
description: Capture Sam's completed 98 Training gym session from a voice or typed recap, inspect the logged-in 98 Training Mac app for the planned programme, reconcile planned and performed work without inventing missing details, and save an idempotent private strength-session record to the Personal Health Dashboard. Use when Sam dictates, records, logs, reconstructs, or reviews a 98 Performance, Hybrid, Groundwork, Capacity, Strength, or other 98 gym workout. Do not use for ordinary runs or rides already sourced from Strava, Wahoo, Garmin, or Apple Health.
---

# Log a 98 Workout

Capture the user-reported work as the performed truth and the 98 Training app as the planned-programme truth. Keep the two visibly separate.

## Boundaries

- Treat the recap and resulting record as private health data. Keep it local and out of Git.
- Use only the logged-in 98 Training Mac app to read the programme. Do not scrape credentials, reverse engineer network traffic, or query unofficial endpoints.
- Never click **Complete Session**, submit app data, edit notes, change programme settings, or alter exercise history.
- Do not infer a load, repetition count, duration, RPE, date, or completion status that the user did not report or clearly confirm.
- Do not estimate calories or make medical, dosing, injury, or treatment claims.
- Preserve the available voice transcription or typed recap verbatim in `source_text`.
- Keep wearable summaries source-separated. Do not manually recreate a Strava, Wahoo, Garmin, WHOOP, or Apple Health workout as a strength record unless the gym work is genuinely separate.

## Workflow

1. Read [references/capture-format.md](references/capture-format.md) before constructing a record.
2. Identify the session date, approximate start time, programme, and any user-reported duration or session RPE. Use `Australia/Sydney` unless the user says the session occurred elsewhere. If an inferred date could select a different workout, ask one concise question before saving. When the date is known but no time is available, use local noon as an explicit date-only placeholder, set `timing_confidence` to `estimated`, and note that the actual time was not reported. When the user says they just finished, the current local time minus a reported duration is an acceptable documented estimate.
3. Preserve the user's recap exactly in `source_text`. Parse it into exercises and individual performed sets, retaining explicit uncertainty in notes.
4. Inspect the 98 Training app for the matching date:
   - The iPhone app runs on macOS through a UIKit wrapper, so its temporary `.app` path can change.
   - Locate the live executable with `pgrep -af 'T98training.app/T98training'`. Derive the exact path ending in `T98training.app`, then use that path with the computer-use app entry point.
   - If the app is not running or not logged in, ask Sam to open or unlock it. Do not retrieve a password.
   - In the Training area, select the matching programme and date. Read the programme name, session name, week, block, series, exercise names, planned sets/reps, tempo, rest, target percentage or RPE, and useful coach notes. Scroll until the entire session has been inspected.
   - Read movement instructions or exercise history only when needed to disambiguate the recap. Do not change anything.
5. Reconcile the two sources:
   - The app supplies only `planned_*`, `program_notes`, programme, and series fields.
   - The user's recap supplies performed set status, reps, load, distance, duration, and effort.
   - Keep app coach notes in `program_notes` or `planned_notes`; keep user-reported outcomes and uncertainty in `notes`.
   - Mark a displayed exercise `skipped` only when the user says it was skipped. Otherwise leave genuinely uncertain work as `unknown` on a partial capture.
   - Ask one concise question when per-side reps, per-hand load, bar total, or set grouping would materially change the totals. Do not guess.
6. Create a stable source ID in this form:

   `voice:<YYYY-MM-DD>:<programme-slug>:w<week-or-x>b<block-or-x>:<session-slug>`

   Use a short `:2` suffix only for a genuine second gym session with the same identity. Reusing an ID must be an idempotent duplicate, not a revision mechanism.
7. Write the proposed JSON to a temporary path outside the repository. Validate it without saving:

   ```bash
   PYTHONPATH=src .venv/bin/python scripts/log_strength_session.py /tmp/strength-session.json
   ```

8. Review the validation summary and calculated totals. If the recap clearly asks or intends to log the completed session and material ambiguities are resolved, save it:

   ```bash
   PYTHONPATH=src .venv/bin/python scripts/log_strength_session.py /tmp/strength-session.json --commit
   ```

   If the user asked only for a preview, reconstruction, or draft, stop after validation.
9. Remove only the exact temporary JSON file after a successful save. Never delete or modify existing health data to repair a mistake without explicit approval.
10. Report the source ID, capture status, exercises, performed sets, reps, volume load, duration/distance if known, and any omitted or uncertain details. Say explicitly when an idempotent duplicate caused no new row.

## Success criteria

- One immutable raw event preserves the transcript and structured payload.
- Planned programme fields are distinguishable from performed fields.
- The relational strength tables contain session, exercise, and set detail.
- Loads retain the reported unit and also normalize to kilograms.
- Repeated logging with the same source ID creates no duplicate record.
- Unknown details remain unknown, and the final summary is factual and non-diagnostic.
