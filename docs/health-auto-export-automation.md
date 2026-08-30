# Health Auto Export Automation Runbook

This runbook keeps Apple Health ingestion reliable for the local dashboard.

## REST and MCP Serve Different Jobs

Keep the REST automation as the primary recurring path. iOS can defer background
exports, but the REST automation can retry and catch up when the phone returns to
the home network. The Health Auto Export v1.1.0 MCP server is useful for interactive
queries and recovery backfills; it stops as soon as the app enters the background,
so it cannot replace an unattended receiver.

The local MCP configuration uses:

```text
Endpoint: http://192.168.4.110:9000/mcp
Authentication: bearer token read from macOS Keychain by a local headers helper
```

Never add the bearer token to this repository, `.env`, shell history, or command
arguments. Keep Health Auto Export open on its Server screen and keep the iPhone
unlocked for the duration of a backfill.

To recover a missing date range into the configured local database:

```bash
PYTHONPATH=src .venv/bin/python scripts/sync_health_auto_export_mcp.py \
  --start 2026-07-11 \
  --end 2026-08-30
```

The sync is resumable: each MCP response and each metric point has a deterministic
identity, so repeating a completed chunk records duplicates rather than double
counting it. The default requests daily aggregates for every metric and preserves
all other MCP categories as raw local records. ECGs, symptoms, state of mind,
medications, cycle tracking, heart notifications, and workouts are not normalized
until their schemas have explicit, tested mappings. Detailed workout routes are
excluded by default; opt in with `--include-workout-routes` when needed.

## Architecture

1. macOS launchd keeps the FastAPI receiver running on port `8000`.
2. Health Auto Export sends REST API batches to `/ingest/apple-health`.
3. The backend preserves raw payloads in `raw_events`, normalizes metrics, and rebuilds affected daily feature rows.

The iPhone can only export health data when iOS allows HealthKit/background work. Background sync is best-effort, so the reliable target is frequent small exports plus an easy manual catch-up path.

## Mac Receiver

macOS launchd cannot reliably run this repo from `~/Documents` because background services may be blocked by privacy controls. For a true always-on LaunchAgent, keep the repo in a non-protected path such as:

```text
~/Developer/personal-health-dashboard
```

Install the LaunchAgent:

```bash
scripts/install_launch_agent.sh
```

Check receiver status:

```bash
scripts/check_health_auto_export_receiver.sh
```

This checks localhost, the current Wi-Fi IP, the shared-secret verify endpoint, and the latest Apple Health ingest timestamp without creating a fake health row.

For monitor-style checks, fail the command when Apple Health is stale:

```bash
FAIL_ON_STALE=1 MAX_APPLE_HEALTH_AGE_HOURS=30 scripts/check_health_auto_export_receiver.sh
```

Install the recurring freshness monitor from the live non-protected checkout:

```bash
cd ~/Developer/personal-health-dashboard
scripts/install_health_auto_export_monitor.sh
```

The monitor runs hourly by default. It verifies that port `8000` is owned by the
expected live checkout, checks localhost and Wi-Fi reachability, verifies the
shared secret without importing probe rows, fails if Apple Health is older than
`MAX_APPLE_HEALTH_AGE_HOURS`, and shows a macOS notification if the Mac Wi-Fi IP
changes. Logs are written to:

```text
logs/health-auto-export-monitor.out.log
logs/health-auto-export-monitor.err.log
```

Stop and remove the LaunchAgent:

```bash
scripts/uninstall_launch_agent.sh
scripts/uninstall_health_auto_export_monitor.sh
```

Logs are written to:

```text
logs/health-dashboard-server.out.log
logs/health-dashboard-server.err.log
```

## Network Safety

Keep the Mac Wi-Fi service on DHCP with automatic DNS on every network. Do not set
\`192.168.6.227\`, the eero gateway, or the Telstra DNS address manually in macOS.
Prefer the Mac's Bonjour hostname and identify the home network by the eero
gateway's address plus MAC address. This avoids coupling the receiver to the
Mac's current DHCP address.

The trusted home signature is:

- Default gateway: \`192.168.4.1\`
- Router MAC: configured as \`HEALTH_DASHBOARD_HOME_ROUTER_MAC\`

The LaunchAgent exposes port \`8000\` to the LAN only when both values match. On
public Wi-Fi, an iPhone hotspot, or no Wi-Fi, it restarts the app on
\`127.0.0.1\` only. Health Auto Export is expected to defer and catch up when the
phone and Mac return to the home network.

The monitor treats travel as a normal deferred state. It must not suggest changing
the iPhone automation to a hotel, lounge, or hotspot address. If the gateway
address is present but its MAC does not match, verify the configured router
identity and leave macOS on DHCP.

Verify travel safety with:

\`\`\`bash
networksetup -getinfo Wi-Fi
lsof -nP -iTCP:8000 -sTCP:LISTEN
curl -fsS http://127.0.0.1:8000/health
\`\`\`

Away from home, the listener must be \`127.0.0.1:8000\`, never \`*:8000\` or the
current travel-network address.

## Stable URL

The preferred URL follows the Mac's current DHCP address through Bonjour:

```text
http://SamCliftons-MacBook-Pro.local:8000/ingest/apple-health
```

If Bonjour does not resolve reliably on the home LAN, reserve the Mac's IP address
in the router and use:

```text
http://<reserved-mac-ip>:8000/ingest/apple-health
```

Verify from Safari on the iPhone before using either URL:

```text
http://<host>:8000/health
```

Expected response:

```json
{"ok":true}
```

## Health Auto Export Settings

Use the existing `Personal Health App Codex` REST API automation.

Recommended settings:

- Automation Type: `REST API`
- URL: `http://<mac-host-or-reserved-ip>:8000/ingest/apple-health`
- Timeout Interval: `60`
- Header: `Authorization: Bearer <shared-secret>`
- Data Type: `Health Metrics`
- Export Format: `JSON`
- Export Version: `v2`
- Date Range: `Default` or `Since Last Sync`
- Batch Requests: `On`
- Sync Cadence: `1 Day`
- Notify on Cache Update: `On`
- Notify When Run: `On`

Prefer generating new automation setup links from the current local config instead of hand-building them:

```bash
scripts/generate_health_auto_export_deeplink.py --enabled
```

The script reads `HEALTH_AUTO_EXPORT_SHARED_SECRET` from the process environment or `.env`, copies the real deep link to the macOS clipboard, and does not print the secret. Paste the copied link into iPhone Safari and approve opening it in Health Auto Export.

If catch-up exports get stuck, temporarily reduce the payload:

- Date Range: `Today` or `Yesterday`
- Select Health Metrics: start with `Steps`, `Active Energy`, `Resting Heart Rate`, `HRV`, `Sleep`, `Weight`, and `Blood Pressure`

For the most reliable baseline, start with a minimal daily automation:

```bash
scripts/generate_health_auto_export_deeplink.py --enabled \
  --metric "Step Count" \
  --metric "Heart Rate" \
  --metric "Active Energy" \
  --metric "Resting Heart Rate" \
  --metric "Heart Rate Variability"
```

Add sleep, blood pressure, workouts, and wider date ranges one category at a time after a successful `200 OK`.

After point-level Apple Health deduplication is deployed, it is safe to add catch-up automations with the same minimal metric set:

```bash
scripts/generate_health_auto_export_deeplink.py \
  --name "Personal Health App Codex Yesterday" \
  --period yesterday \
  --enabled
```

```bash
scripts/generate_health_auto_export_deeplink.py \
  --name "Personal Health App Codex 7 Day Catchup" \
  --period previous7days \
  --enabled
```

The backend assigns deterministic IDs to Health Auto Export v2 metric points and collapses repeated aggregate revisions in daily rollups, so repeated catch-up exports do not double count steps, active energy, or other additive daily metrics.

## Verification Without Importing Data

Use the verify endpoint to check that the receiver and shared secret agree:

```bash
scripts/check_health_auto_export_receiver.sh
```

Directly, with the secret loaded in the environment:

```bash
curl -fsS \
  -H "Authorization: Bearer ${HEALTH_AUTO_EXPORT_SHARED_SECRET}" \
  http://127.0.0.1:8000/ingest/apple-health/verify
```

Expected response:

```json
{"ok":true,"provider":"apple_health"}
```

## Manual Catch-Up

Do not use the left-menu `Manual Export`; that creates file exports. Use:

```text
Automated -> Personal Health App Codex -> Export Existing Data -> Manual Export
```

The Activity Logs should show `Manual Export` or `App Background` with `Succeeded`. Server logs should show:

```text
POST /ingest/apple-health HTTP/1.1" 200 OK
```

## Known Constraints

Health Auto Export cannot reliably read HealthKit data while the iPhone is locked, and iOS may defer background execution. Keep the phone unlocked during a large catch-up export. For routine sync, small daily batches are much less likely to stall than a multi-week catch-up.
