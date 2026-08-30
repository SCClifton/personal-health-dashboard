# Health Auto Export Troubleshooting - 2026-06-01

## Summary

Health Auto Export is posting to the dashboard again after replacing the broad crashing automation with a minimal daily REST automation.

## Verified Receiver State

- Active server checkout: `/Users/samuelclifton/Developer/personal-health-dashboard`
- Server health:
  - `http://127.0.0.1:8000/health` returned `{"ok": true}`
  - `http://192.168.4.219:8000/health` returned `{"ok": true}`
- Active Mac LAN IP observed this session: `192.168.4.219`
- No listener was present on temporary setup port `8011`.
- `apple_health` connector status was stale at `2026-05-17T22:56:24.400641` before the fix.
- After the fix, `/api/connectors` reported `apple_health.last_sync_at` as `2026-05-31T23:51:54.295166`.
- Active SQLite check:
  - Before: `raw_events` had 10 `apple_health` rows.
  - After: `raw_events` had 12 `apple_health` rows.
  - Latest `apple_health.received_at` after the successful phone import was `2026-05-31 23:51:54.295166`.

## Phone-Side Changes

- Opened Health Auto Export through iPhone Mirroring.
- Confirmed existing automation: `Personal Health App Codex`.
- Updated the automation REST endpoint from an old LAN address to:
  - `http://192.168.4.219:8000/ingest/apple-health`
- Left the existing Authorization value in place and did not reveal or rewrite the token.
- Health Auto Export displayed `Success! Saved successfully!` after the endpoint update.
- Disabled the original broad `Personal Health App Codex` automation to stop the foreground crash loop.
- Imported a new minimal automation named `Personal Health App Codex Current` using the active project shared secret.
- Disabled the earlier wrong-token `Personal Health App Codex Minimal` automation after it produced a `401 Unauthorized`.

## Failure Observed

- On launch, Health Auto Export repeatedly started `Sync in progress...`.
- The sync progressed partway, reaching roughly the 80-90% range on one run, then Health Auto Export crashed back to the iPhone home screen.
- Server access logs showed no `POST /ingest/apple-health` during the observed attempts.
- This confirms the current blocker is still inside Health Auto Export / HealthKit export preparation rather than the dashboard receiver.
- A later minimal automation with an old/short token reached the server but returned `401 Unauthorized`; the server-side shared secret was then validated locally and a corrected current-secret automation was imported.

## Working Scope Reduction

The working automation uses a small daily payload:

- Date range: `Today`
- Export format: `JSON`
- Export version: `v2`
- Summarize data: enabled
- Time grouping: `Days`
- Batch requests: enabled
- Metrics: `Step Count`, `Heart Rate`, `Active Energy`, `Resting Heart Rate`, `Heart Rate Variability`
- Workouts, routes, symptoms, and broad all-metric export remain off.

## Next Steps

1. Keep `Personal Health App Codex Current` enabled as the daily Health Auto Export job.
2. Keep the original `Personal Health App Codex` disabled until it can be safely deleted or replaced.
3. Keep `Personal Health App Codex Minimal` disabled because it used the wrong token and produced `401 Unauthorized`.
4. Reserve the Mac IP in the router, or switch the automation URL to a stable hostname after testing from iPhone Safari.
5. Expand only one category at a time:
   - Add `Yesterday` as a one-off catch-up.
   - Add sleep next.
   - Add blood pressure next if Hilo/Aktiia is writing to Apple Health.
   - Add workouts last, still without routes or high-frequency series.
6. After each expansion, verify:
   - Server log has `POST /ingest/apple-health HTTP/1.1" 200 OK`
   - `/api/connectors` shows a fresh `apple_health.last_sync_at`
   - `raw_events` has new `provider='apple_health'` rows
7. For future rebuilds, generate the automation link with:
   - `scripts/generate_health_auto_export_deeplink.py --enabled`
   - This reads the current local secret and copies the setup link without printing the secret.
8. Use `scripts/check_health_auto_export_receiver.sh` for future health checks. It verifies `/health`, the current Wi-Fi URL, the shared-secret verify endpoint, and Apple Health freshness without importing a fake probe row.

## Integration Buildout Note

Keep Apple Health as the broad fallback path, not the preferred source where direct integrations are richer. WHOOP remains the direct source for recovery, cycles, sleep, workouts, and body measurements where available. Garmin remains approval-gated for official API access; near-term Garmin-derived body/activity data should flow through Apple Health, while richer run-performance detail should use Strava or future Garmin/FIT import. Nutrition should start with MyFitnessPal Premium export CSV/ZIP rather than password-based scraping.
