# Credential Management

This project uses `.env` for local configuration and supports 1Password CLI (`op`) for loading secrets into a shell session or a single local process.

Sam authorizes agents to use `op` for project-specific credential work, including checking field presence, reading values into environment variables, and creating/updating API credential items whose fields match `.env.example`.

Guardrails:

- Do not print secret values to terminal output or chat.
- Do not commit `.env`, token databases, exports, or API credentials.
- Do not write plaintext secrets to disk unless Sam explicitly asks for a local `.env` update.
- Do not use browser password managers.
- Do not use passwords for scraping or login-protected data extraction.
- Ask before using credentials to log into a third-party website or provider dashboard, creating OAuth/API credentials, or changing account/security settings.
- If an `op` command needs to reveal a field, capture it directly into an environment variable or local command input; do not echo it.

## Recommended 1Password Structure

Use one item when possible:

```text
Item title: Personal Health Dashboard
Category: API Credential
```

If you already created a WHOOP-specific item, this is also fine:

```text
Item title: Personal Health Dashboard Whoop API
Category: API Credential
```

Provider-specific items should use the same naming pattern:

```text
Item title: Personal Health Dashboard Oura API
Category: API Credential
```

Current known project items:

```text
WHOOP:  Catherine & Sam / Personal Health Dashboard Whoop API
Strava: Private / Strava API Credential
Oura:   Catherine & Sam / Personal Health Dashboard Oura API
```

For health reports, use the multi-item loader so Strava and Oura are not missed:

```bash
scripts/check_health_op_env.sh
scripts/run_health_report_with_op_env.sh .venv/bin/python scripts/auto_health_report.py
```

Field labels must exactly match `.env.example`:

```text
APP_SECRET_KEY
HEALTH_AUTO_EXPORT_SHARED_SECRET
WHOOP_CLIENT_ID
WHOOP_CLIENT_SECRET
WHOOP_REDIRECT_URI
STRAVA_CLIENT_ID
STRAVA_CLIENT_SECRET
STRAVA_REDIRECT_URI
STRAVA_WEBHOOK_VERIFY_TOKEN
OURA_CLIENT_ID
OURA_CLIENT_SECRET
OURA_REDIRECT_URI
OURA_PERSONAL_ACCESS_TOKEN
```

## WHOOP Fields

For the item `Personal Health Dashboard Whoop API`, make sure these labels are exact:

```text
WHOOP_CLIENT_ID
WHOOP_CLIENT_SECRET
WHOOP_REDIRECT_URI
```

Use:

```text
WHOOP_REDIRECT_URI=http://localhost:8000/auth/whoop/callback
```

The current local `.env` still has empty WHOOP client fields. After saving the values in 1Password, load them with:

```bash
eval "$(op signin)"
OP_ITEM="Personal Health Dashboard Whoop API" source scripts/load_op_env.sh
```

If multiple 1Password accounts are configured, include `OP_ACCOUNT`. For the current WHOOP item:

```bash
op signin --account my.1password.com
OP_ACCOUNT="my.1password.com" OP_VAULT="Catherine & Sam" OP_ITEM="Personal Health Dashboard Whoop API" source scripts/load_op_env.sh
```

If the item is in another specific vault, include `OP_VAULT`:

```bash
OP_VAULT="Clifton Family" OP_ITEM="Personal Health Dashboard Whoop API" source scripts/load_op_env.sh
```

Then verify:

```bash
env | grep '^WHOOP_' | sed 's/=.*/=set/'
```

Or check the 1Password item directly without printing values:

```bash
OP_ACCOUNT="my.1password.com" OP_VAULT="Catherine & Sam" OP_ITEM="Personal Health Dashboard Whoop API" scripts/check_op_env.sh
```

To start the app with values loaded only into the server process:

```bash
OP_VAULT="Catherine & Sam" OP_KEYS="WHOOP_CLIENT_ID WHOOP_CLIENT_SECRET WHOOP_REDIRECT_URI" OP_ITEM="Personal Health Dashboard Whoop API" scripts/run_with_op_env.sh
```

For repeated commands in the same terminal session, set the repo's 1Password context once:

```bash
source scripts/setup_op_session.sh
scripts/check_op_env.sh
scripts/run_with_op_env.sh
```

To update the WHOOP credential fields without echoing secrets:

```bash
scripts/update_whoop_op_credentials.sh
```

## Oura Fields

For the item `Personal Health Dashboard Oura API`, make sure these labels are exact:

```text
OURA_CLIENT_ID
OURA_CLIENT_SECRET
OURA_REDIRECT_URI
OURA_PERSONAL_ACCESS_TOKEN
```

Use:

```text
OURA_REDIRECT_URI=http://localhost:8000/auth/oura/callback
```

To update the Oura credential fields without echoing secrets:

```bash
OP_ACCOUNT="my.1password.com" OP_VAULT="Catherine & Sam" OP_ITEM="Personal Health Dashboard Oura API" scripts/update_oura_op_credentials.sh
```

Or check the 1Password item directly without printing values:

```bash
OP_ACCOUNT="my.1password.com" OP_VAULT="Catherine & Sam" OP_ITEM="Personal Health Dashboard Oura API" scripts/check_op_env.sh OURA_CLIENT_ID OURA_CLIENT_SECRET OURA_REDIRECT_URI
```

App credentials do not create direct Oura data access by themselves. After the
item is loaded, direct Oura sync still needs either:

```text
1. A local OAuth token stored by visiting /auth/oura/start and approving access.
2. OURA_PERSONAL_ACCESS_TOKEN set in the Oura item for the local fallback path.
```

Apple Health rows whose source text mentions Oura are fallback context only;
claim direct Oura data only when provider/source rows are from `oura`.

## Strava Fields

The current Strava API credential item is `Private / Strava API Credential`.

### Oura OAuth recovery snapshot

The Oura app credentials and the user-authorised OAuth token are deliberately
separate 1Password items:

- app credentials: `Catherine & Sam / Personal Health Dashboard Oura API`
- token recovery snapshot: `Catherine & Sam / Personal Health Dashboard Oura OAuth Token`

The local SQLite `oauth_tokens` row remains the runtime source because Oura can
rotate access and refresh tokens. After a new Oura authorisation, refresh the
recovery snapshot without printing either secret:

```bash
HEALTH_DB_PATH=/absolute/path/to/health_dashboard.db scripts/backup_oura_oauth_token_to_op.sh
```
Make sure these labels are exact:

```text
STRAVA_CLIENT_ID
STRAVA_CLIENT_SECRET
STRAVA_REDIRECT_URI
STRAVA_WEBHOOK_VERIFY_TOKEN
STRAVA_WEBHOOK_SIGNING_SECRET
```

Check without printing values:

```bash
OP_ACCOUNT="my.1password.com" OP_VAULT="Private" OP_ITEM="Strava API Credential" scripts/check_op_env.sh STRAVA_CLIENT_ID STRAVA_CLIENT_SECRET STRAVA_REDIRECT_URI STRAVA_WEBHOOK_VERIFY_TOKEN
```

If Strava has an expired OAuth token but the API credential item is not loaded,
token refresh can fail even though the stored OAuth row exists. Use
`scripts/run_health_report_with_op_env.sh` for daily reports so the Private
vault Strava item is loaded into the process.

If you want the project to auto-load a combined item, rename or copy fields into an item called `Personal Health Dashboard`, then run:

```bash
source scripts/load_op_env.sh
```

## Local `.env`

For persistent local development, values may be written from 1Password into `.env` only after Sam explicitly asks for that. Do not commit `.env`.

Required for WHOOP connector status to become `configured`:

```text
WHOOP_CLIENT_ID=<saved client id>
WHOOP_CLIENT_SECRET=<saved client secret>
WHOOP_REDIRECT_URI=http://localhost:8000/auth/whoop/callback
```

Restart the server after changing `.env`.

## Verification

```bash
curl -s http://127.0.0.1:8000/api/connectors
```

Expected before OAuth authorization:

```text
whoop: configured
```

Expected after visiting `/auth/whoop/start` and approving access:

```text
whoop: connected
```

After authorization, pull WHOOP data into local raw events and dashboard metrics:

```bash
curl -X POST 'http://127.0.0.1:8000/sync/whoop?days=30'
```
