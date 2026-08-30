# Claude Code Health Collaboration Prompt

Use this prompt when opening Claude Code in this project folder:

```text
You are Claude Code working with Sam's private local-first Personal Health Dashboard.

Project directory:
/Users/samuelclifton/Documents/Projects/personal-health-dashboard

Before writing code, read:
- AGENTS.md
- README.md
- docs/credential-management.md
- docs/multi-agent-workflow.md
- docs/agent-coach-prompt.md
- src/health_dashboard/models.py
- src/health_dashboard/schema.sql
- src/health_dashboard/services/medication.py
- src/health_dashboard/api/routes.py
- src/health_dashboard/dashboard/render.py

Operating constraints:
- Keep all health data local/private.
- Do not print secrets or commit .env, databases, exports, transcripts, or credentials.
- Do not make medical, dosing, or treatment recommendations.
- Preserve raw source evidence and keep clinician/source attribution visible.
- Treat GLP-1/tirzepatide content as tracking context only, not advice.
- Use official APIs, connected MCPs, or user-provided exports only. No password scraping.
- Follow the repo's multi-agent workflow for planned code changes: create/use a GitHub issue and a per-issue worktree via scripts/start_issue.sh.

Current coordination context:
- Codex has working local Strava API credentials in 1Password and successfully synced Strava data into the local SQLite database.
- Codex attempted to configure Strava MCP for Codex, but Strava's official MCP currently authenticates for Claude clients and Codex login is blocked. Use the local Strava API connector for dashboard ingestion unless Strava/Codex compatibility changes.
- Claude Code can use Strava MCP directly if authenticated with:
  claude mcp add --transport http strava-mcp https://mcp.strava.com/mcp
  Then run /mcp in Claude Code and complete Strava OAuth.
- The dashboard already supports tirzepatide dose logging through src/health_dashboard/services/medication.py and POST /medication/tirzepatide.
- The GLP-1 dashboard route is /dashboard/glp1 and currently renders tirzepatide dose, weight, calories, protein, BP, resting HR, sleep, and workouts.

Task:
Help extend the health dashboard so Sam can manage a clinician-guided tirzepatide dose increase and watch biomarkers around the change.

Source discovery:
1. Look for the Otter transcript or email/meeting context involving Vanessa from Everlab/Evalab on the evening of 2026-06-08 Australia/Sydney time.
2. If using Otter MCP, fetch the transcript through the authenticated MCP and save only a concise source-aware summary under a gitignored local_exports path. Do not commit raw transcript text unless Sam explicitly asks.
3. If Otter is unavailable, ask Sam for the transcript/export or use connected email/calendar sources only with explicit source attribution.

Implementation goals:
1. Add a durable "dose-change context" concept that records:
   - medication name
   - prior dose if known
   - planned/new dose if known
   - planned/effective date
   - clinician/source name
   - source type and source reference
   - preparation notes, monitoring notes, and follow-up questions
2. Keep actual dose administrations separate from planned dose-change context. Do not overwrite the existing MedicationDose model behavior.
3. Add dashboard visibility for the dose-change window:
   - a marker or card on /dashboard/glp1 for upcoming/current dose-change context
   - pre/post windows for weight, appetite/nutrition adherence, GI symptoms if logged, sleep, resting HR, HRV, BP, training load, and workouts
   - clear copy that this is monitoring context and not medical advice
4. Add tests for:
   - dose-change context persistence
   - timezone handling for Australia/Sydney
   - dashboard render when context exists
   - dashboard render when no context exists
5. Update README or docs with the local workflow for adding a clinician-guided dose-change context.

Data and safety boundaries:
- Do not infer or recommend a dose. Only store what the clinician/source says or what Sam explicitly logs.
- If the transcript is ambiguous, mark fields as unknown rather than guessing.
- Any implications should be phrased as tracking questions and operational follow-ups, not clinical advice.
- Do not transmit health data to third parties beyond the explicitly authorized MCP/source being used.

Verification:
Run:
PYTHONPATH=src .venv/bin/python -m pytest -q

Report:
- files changed
- tests run and result
- any source access gaps, especially whether Otter MCP was available and authenticated
- any fields left unknown because the transcript/source did not support them
```

## Notes For Sam

Open Claude Code in:

```bash
cd /Users/samuelclifton/Documents/Projects/personal-health-dashboard
claude
```

Then paste the prompt above.
