from __future__ import annotations

import secrets
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from health_dashboard.api.schemas import ImportResult, TirzepatideDoseContextIn, TirzepatideDoseIn
from health_dashboard.config import Settings, get_settings
from health_dashboard.connectors.apple_health import metrics_from_apple_record, records_from_health_auto_export
from health_dashboard.connectors.csv_imports import parse_csv_metrics, parse_zip_metrics
from health_dashboard.connectors.oura import OuraConnector, oura_token_expiry
from health_dashboard.connectors.status import all_connector_info, sync_connector_state
from health_dashboard.connectors.strava import StravaConnector, strava_token_expiry, verify_strava_signature
from health_dashboard.connectors.whoop import WhoopConnector, token_expiry
from health_dashboard.dashboard.render import (
    SourceHealthRow,
    render_cardiometabolic,
    render_coaching_dashboard,
    render_connector_status,
    render_correlation_lab,
    render_dashboard,
    render_data_quality,
    render_glp1_dashboard,
    render_overview,
    render_recovery_sleep,
    render_runs_dashboard,
    render_training_load,
)
from health_dashboard.db import get_db
from health_dashboard.models import NormalizedMetric, OAuthToken, RawEvent
from health_dashboard.services.ingestion import daily_feature_rows, rebuild_daily_features, store_raw_event
from health_dashboard.services.coaching import (
    active_goal,
    adherence_summary,
    build_coaching_snapshot,
    coaching_missing_data_actions,
    default_goal_from_rows,
    goal_progress,
    upsert_active_goal,
)
from health_dashboard.services.medication import latest_dose_change_context, log_tirzepatide_dose, upsert_dose_change_context
from health_dashboard.services.oura_sync import sync_oura
from health_dashboard.services.run_analysis import analyze_strava_run_recovery, recent_strava_runs
from health_dashboard.services.strava_sync import sync_strava, sync_strava_runs
from health_dashboard.services.sync_queue import provider_sync_slot, sync_queue_snapshot
from health_dashboard.services.time import local_date
from health_dashboard.services.whoop_sync import sync_whoop


router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"ok": True}


@router.get("/privacy", response_class=HTMLResponse)
def privacy() -> str:
    return """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Privacy Policy - Personal Health Dashboard</title>
        <style>
          body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.5; max-width: 760px; margin: 40px auto; padding: 0 20px; color: #17211d; }
          h1 { font-size: 28px; }
        </style>
      </head>
      <body>
        <h1>Privacy Policy</h1>
        <p>Personal Health Dashboard is a local-first health data application intended for private personal use.</p>
        <p>Health data and API tokens are stored locally on the user's machine by default. The application does not sell health data, does not use password-based scraping, and does not share personal health data with third parties except when the user explicitly connects a provider API or imports data from that provider.</p>
        <p>Connected providers such as WHOOP, Strava, Oura, and Health Auto Export are used only to retrieve or receive the user's own health and fitness data for local analysis. Correlations shown by the dashboard are exploratory and are not medical diagnosis or treatment advice.</p>
      </body>
    </html>
    """


@router.get("/", response_class=HTMLResponse)
def overview(db: Session = Depends(get_db)) -> str:
    rows = daily_feature_rows(db, days=180)
    return render_overview(rows, get_settings().height_cm)


@router.get("/dashboard/coach", response_class=HTMLResponse)
def coach_dashboard(db: Session = Depends(get_db)) -> str:
    rows = daily_feature_rows(db, days=180)
    goal = active_goal(db) or default_goal_from_rows(rows)
    progress = goal_progress(goal, rows)
    adherence = adherence_summary(rows, goal)
    return render_coaching_dashboard(rows, progress, adherence, coaching_missing_data_actions(db, rows))


@router.post("/coach/goal")
def save_coaching_goal(
    start_date: date = Form(...),
    target_date: date = Form(...),
    start_weight_kg: float = Form(...),
    target_weight_kg: float = Form(...),
    daily_calorie_target: str | None = Form(default=None),
    daily_protein_target_g: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    upsert_active_goal(
        db,
        start_date=start_date,
        target_date=target_date,
        start_weight_kg=start_weight_kg,
        target_weight_kg=target_weight_kg,
        daily_calorie_target=optional_float(daily_calorie_target),
        daily_protein_target_g=optional_float(daily_protein_target_g),
        notes=notes or None,
    )
    db.commit()
    return RedirectResponse("/dashboard/coach", status_code=303)


@router.get("/api/coach/snapshot")
def coach_snapshot(days: int = Query(default=90, ge=7, le=365), db: Session = Depends(get_db)) -> dict:
    rows = daily_feature_rows(db, days=days)
    snapshot = build_coaching_snapshot(db, rows, days=days)
    return {
        "generated_for_days": snapshot.generated_for_days,
        "goal": snapshot.goal,
        "adherence": snapshot.adherence,
        "training_sleep": snapshot.training_sleep,
        "source_freshness": snapshot.source_freshness,
        "missing_data_actions": snapshot.missing_data_actions,
    }


@router.get("/dashboard/cardiometabolic", response_class=HTMLResponse)
def cardiometabolic(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> str:
    rows = daily_feature_rows(db, days=210)
    return render_cardiometabolic(rows, settings.height_cm)


@router.get("/dashboard/glp1", response_class=HTMLResponse)
def glp1(db: Session = Depends(get_db)) -> str:
    rows = daily_feature_rows(db, days=180)
    return render_glp1_dashboard(rows, latest_dose_change_context(db, medication_name="tirzepatide"), height_cm=get_settings().height_cm)


@router.get("/dashboard/sleep", response_class=HTMLResponse)
def sleep_recovery(db: Session = Depends(get_db)) -> str:
    rows = daily_feature_rows(db, days=90)
    return render_recovery_sleep(rows)


@router.get("/dashboard/training", response_class=HTMLResponse)
def training(lag: int = Query(default=1), db: Session = Depends(get_db)) -> str:
    rows = daily_feature_rows(db, days=90)
    return render_training_load(rows, lag_days=lag if lag in {0, 1, 2, 7} else 1)


@router.get("/dashboard/runs", response_class=HTMLResponse)
def runs_dashboard(days: int = Query(default=14, ge=1, le=90), db: Session = Depends(get_db)) -> str:
    runs = recent_strava_runs(db, days=days)
    analysis = analyze_strava_run_recovery(db, runs[0].activity_id) if runs else None
    return render_runs_dashboard(runs, analysis, days=days)


@router.get("/api/runs/recent")
def recent_runs(days: int = Query(default=14, ge=1, le=90), db: Session = Depends(get_db)) -> list[dict]:
    return [asdict(item) for item in recent_strava_runs(db, days=days)]


@router.get("/api/runs/{activity_id}/recovery")
def run_recovery(activity_id: str, db: Session = Depends(get_db)) -> dict:
    return asdict(analyze_strava_run_recovery(db, activity_id))


@router.get("/dashboard/correlation-lab", response_class=HTMLResponse)
def correlation_lab(
    metric_a: str = Query(default="training_load"),
    metric_b: str = Query(default="hrv"),
    lag: int = Query(default=1),
    days: int = Query(default=180),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> str:
    return render_correlation_lab(
        daily_feature_rows(db, days=max(days, 180)),
        height_cm=settings.height_cm,
        metric_a=metric_a,
        metric_b=metric_b,
        lag_days=lag if lag in {0, 1, 2, 7} else 1,
        days=days if days in {30, 90, 180, 365} else 180,
    )


@router.get("/connectors", response_class=HTMLResponse)
def connector_status(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> str:
    return RedirectResponse("/dashboard/data-quality", status_code=303)


@router.get("/dashboard/data-quality", response_class=HTMLResponse)
def data_quality(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> str:
    infos = all_connector_info(settings, db)
    sync_connector_state(db, infos)
    db.commit()
    rows = daily_feature_rows(db, days=45)
    return render_data_quality(source_health_rows(db, infos), data_quality_warnings(db, rows), sync_queue_snapshot())


@router.get("/api/connectors")
def connector_status_json(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> list[dict]:
    infos = all_connector_info(settings, db)
    return [info.__dict__ | {"status": info.status.value} for info in infos]


@router.post("/ingest/apple-health", response_model=ImportResult)
async def ingest_apple_health(
    request: Request,
    authorization: str | None = Header(default=None),
    x_health_auto_export_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ImportResult:
    if not settings.health_auto_export_shared_secret:
        raise HTTPException(status_code=503, detail="HEALTH_AUTO_EXPORT_SHARED_SECRET is not configured")
    supplied = x_health_auto_export_secret
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization.split(" ", 1)[1]
    if not supplied or not secrets.compare_digest(supplied, settings.health_auto_export_shared_secret):
        raise HTTPException(status_code=401, detail="Invalid Health Auto Export secret")

    payload = await request.json()
    records = records_from_health_auto_export(payload)
    batch_id = str(uuid4())
    imported = 0
    duplicates = 0
    impacted_dates: list[date] = []
    for record in records:
        metrics = metrics_from_apple_record(record)
        _, created = store_raw_event(
            db,
            provider="apple_health",
            payload=record,
            import_batch_id=batch_id,
            permissions_scope=record.get("permissions_scope") or record.get("type"),
            metrics=metrics,
        )
        imported += int(created)
        duplicates += int(not created)
        if created:
            impacted_dates.extend(local_date(metric.observed_start, settings.local_timezone) for metric in metrics)
    if impacted_dates:
        rebuild_daily_features(db, start=min(impacted_dates), end=max(impacted_dates))
    db.commit()
    return ImportResult(provider="apple_health", imported=imported, duplicates=duplicates, batch_id=batch_id)


@router.get("/ingest/apple-health/verify")
def verify_apple_health_ingest_secret(
    authorization: str | None = Header(default=None),
    x_health_auto_export_secret: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not settings.health_auto_export_shared_secret:
        raise HTTPException(status_code=503, detail="HEALTH_AUTO_EXPORT_SHARED_SECRET is not configured")
    supplied = x_health_auto_export_secret
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization.split(" ", 1)[1]
    if not supplied or not secrets.compare_digest(supplied, settings.health_auto_export_shared_secret):
        raise HTTPException(status_code=401, detail="Invalid Health Auto Export secret")
    return {"ok": True, "provider": "apple_health"}


@router.post("/imports/{provider}", response_model=ImportResult)
async def import_file(
    provider: str,
    file: UploadFile = File(...),
    source: str = Form(default="manual"),
    db: Session = Depends(get_db),
) -> ImportResult:
    content = await file.read()
    rows = parse_zip_metrics(content, provider=provider, source=source) if file.filename and file.filename.lower().endswith(".zip") else parse_csv_metrics(content, provider=provider, source=source)
    batch_id = str(uuid4())
    imported = 0
    duplicates = 0
    for payload, metrics in rows:
        _, created = store_raw_event(db, provider=provider, payload=payload, import_batch_id=batch_id, metrics=metrics)
        imported += int(created)
        duplicates += int(not created)
    rebuild_daily_features(db)
    db.commit()
    return ImportResult(provider=provider, imported=imported, duplicates=duplicates, batch_id=batch_id)


@router.post("/medication/tirzepatide")
def medication_tirzepatide(payload: TirzepatideDoseIn, db: Session = Depends(get_db)) -> dict:
    dose = log_tirzepatide_dose(db, **payload.model_dump())
    db.commit()
    return {"id": dose.id, "medication_name": dose.medication_name, "dose_mg": dose.dose_mg, "taken_at": dose.taken_at.isoformat()}


@router.post("/medication/tirzepatide/dose-context")
def medication_tirzepatide_dose_context(payload: TirzepatideDoseContextIn, db: Session = Depends(get_db)) -> dict:
    context = upsert_dose_change_context(db, medication_name="tirzepatide", **payload.model_dump())
    db.commit()
    return {
        "id": context.id,
        "medication_name": context.medication_name,
        "prior_dose_mg": context.prior_dose_mg,
        "planned_dose_mg": context.planned_dose_mg,
        "planned_start_date": context.planned_start_date.isoformat() if context.planned_start_date else None,
        "clinician_name": context.clinician_name,
        "source_type": context.source_type,
        "source_reference": context.source_reference,
    }


@router.get("/api/raw-events")
def raw_events(db: Session = Depends(get_db), limit: int = 50) -> list[dict]:
    rows = db.query(RawEvent).order_by(RawEvent.received_at.desc()).limit(limit).all()
    return [
        {
            "id": row.id,
            "provider": row.provider,
            "source_record_id": row.source_record_id,
            "observed_start": row.observed_start,
            "payload_hash": row.payload_hash,
        }
        for row in rows
    ]


@router.post("/admin/rebuild-daily-features")
def rebuild_features(start: date | None = None, end: date | None = None, db: Session = Depends(get_db)) -> dict:
    rebuild_daily_features(db, start=start, end=end)
    db.commit()
    return {"ok": True}


@router.get("/auth/whoop/start")
def whoop_start(settings: Settings = Depends(get_settings)) -> RedirectResponse:
    return RedirectResponse(WhoopConnector(settings).authorization_url(state=secrets.token_urlsafe(8)))


@router.get("/auth/whoop/callback")
async def whoop_callback(code: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    token_payload = await WhoopConnector(settings).exchange_code(code)
    save_token(db, "whoop", token_payload, token_expiry(token_payload))
    db.commit()
    return {"ok": True, "provider": "whoop", "scope": token_payload.get("scope")}


@router.post("/sync/whoop")
async def whoop_sync(
    days: int = Query(default=30, ge=1, le=365),
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    sync_end = end or datetime.now(timezone.utc)
    sync_start = start or sync_end - timedelta(days=days)
    try:
        async with provider_sync_slot("whoop"):
            result = await sync_whoop(db, settings, start=sync_start, end=sync_end)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return result


@router.get("/auth/strava/start")
def strava_start(settings: Settings = Depends(get_settings)) -> RedirectResponse:
    return RedirectResponse(StravaConnector(settings).authorization_url(state=secrets.token_urlsafe(16)))


@router.get("/auth/strava/callback")
async def strava_callback(code: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    token_payload = await StravaConnector(settings).exchange_code(code)
    save_token(db, "strava", token_payload, strava_token_expiry(token_payload))
    db.commit()
    return {"ok": True, "provider": "strava", "scope": token_payload.get("scope")}


@router.post("/sync/strava")
async def strava_sync(
    days: int = Query(default=30, ge=1, le=365),
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    sync_end = end or datetime.now(timezone.utc)
    sync_start = start or sync_end - timedelta(days=days)
    try:
        async with provider_sync_slot("strava"):
            result = await sync_strava(db, settings, start=sync_start, end=sync_end)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return result


@router.post("/sync/strava/runs")
async def strava_runs_sync(
    days: int = Query(default=7, ge=1, le=90),
    activity_id: int | None = Query(default=None),
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    sync_end = end or datetime.now(timezone.utc)
    sync_start = start or sync_end - timedelta(days=days)
    try:
        async with provider_sync_slot("strava"):
            result = await sync_strava_runs(db, settings, start=sync_start, end=sync_end, activity_id=activity_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return result


@router.post("/sync/oura")
async def oura_sync(
    days: int = Query(default=30, ge=1, le=365),
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    sync_end = end or datetime.now(timezone.utc)
    sync_start = start or sync_end - timedelta(days=days)
    try:
        async with provider_sync_slot("oura"):
            result = await sync_oura(db, settings, start=sync_start, end=sync_end)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return result


@router.get("/webhooks/strava")
def strava_webhook_challenge(
    hub_mode: str | None = None,
    hub_verify_token: str | None = None,
    hub_challenge: str | None = None,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    if settings.strava_webhook_verify_token and hub_verify_token != settings.strava_webhook_verify_token:
        raise HTTPException(status_code=403, detail="Invalid Strava verify token")
    return JSONResponse({"hub.challenge": hub_challenge})


@router.post("/webhooks/strava")
async def strava_webhook_event(
    request: Request,
    x_strava_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    body = await request.body()
    if not verify_strava_signature(body, x_strava_signature, settings.strava_webhook_signing_secret):
        raise HTTPException(status_code=401, detail="Invalid Strava signature")
    payload = await request.json()
    store_raw_event(db, provider="strava_webhook", payload=payload)
    db.commit()
    return {"ok": True}


@router.get("/auth/oura/start")
def oura_start(settings: Settings = Depends(get_settings)) -> RedirectResponse:
    return RedirectResponse(OuraConnector(settings).authorization_url(state=secrets.token_urlsafe(16)))


@router.get("/auth/oura/callback")
async def oura_callback(code: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    token_payload = await OuraConnector(settings).exchange_code(code)
    save_token(db, "oura", token_payload, oura_token_expiry(token_payload))
    db.commit()
    return {"ok": True, "provider": "oura", "scope": token_payload.get("scope")}


def save_token(db: Session, provider: str, token_payload: dict, expires_at) -> OAuthToken:
    token = db.get(OAuthToken, provider)
    if token is None:
        token = OAuthToken(provider=provider)
        db.add(token)
    token.access_token = token_payload.get("access_token")
    token.refresh_token = token_payload.get("refresh_token")
    token.token_type = token_payload.get("token_type")
    token.scope = token_payload.get("scope")
    token.expires_at = expires_at
    db.flush()
    return token


def source_health_rows(db: Session, infos) -> list[SourceHealthRow]:
    last_raw = dict(db.query(RawEvent.provider, func.max(RawEvent.received_at)).group_by(RawEvent.provider).all())
    last_normalized = dict(db.query(NormalizedMetric.provider, func.max(NormalizedMetric.created_at)).group_by(NormalizedMetric.provider).all())
    actions = {"whoop": "/sync/whoop?days=30", "strava": "/sync/strava?days=30", "oura": "/sync/oura?days=30"}
    rows: list[SourceHealthRow] = []
    for info in infos:
        provider = info.name
        raw_at = last_raw.get(provider)
        normalized_at = last_normalized.get(provider)
        rows.append(
            SourceHealthRow(
                name=provider,
                status=info.status.value,
                detail=info.detail,
                next_action=info.next_action,
                last_sync_at=info.last_sync_at.isoformat() if info.last_sync_at else "-",
                last_raw_event_at=raw_at.isoformat() if raw_at else "-",
                last_normalized_metric_at=normalized_at.isoformat() if normalized_at else "-",
                action=actions.get(provider),
            )
        )
    return rows


def data_quality_warnings(db: Session, rows) -> list[str]:
    warnings: list[str] = []
    latest_apple_raw = db.query(func.max(RawEvent.received_at)).filter(RawEvent.provider == "apple_health").scalar()
    if latest_apple_raw is None or latest_apple_raw.date() < date.today():
        warnings.append("Apple Health has not posted today.")
    bp_rows = [row for row in rows if row.systolic_bp is not None or row.diastolic_bp is not None]
    if not bp_rows:
        warnings.append("Blood pressure is missing. Hilo BP should appear after Apple Health receives and posts those readings.")
    nutrition_days = sum(1 for row in rows[-30:] if row.calories is not None or row.protein is not None)
    if nutrition_days < 7:
        warnings.append("Nutrition is sparse in the last 30 days.")
    weight_days = sum(1 for row in rows[-30:] if row.weight is not None)
    if weight_days < 7:
        warnings.append("Weight is sparse in the last 30 days.")
    protein_days = sum(1 for row in rows[-30:] if row.protein is not None)
    if protein_days < 7:
        warnings.append("Protein logging is sparse in the last 30 days.")
    for provider in ("whoop", "strava"):
        latest = db.query(func.max(NormalizedMetric.observed_start)).filter(NormalizedMetric.provider == provider).scalar()
        if latest is None:
            warnings.append(f"{provider.upper()} has not landed raw data yet.")
        elif latest.date() < date.today() - timedelta(days=2):
            warnings.append(f"{provider.upper()} data is stale after {latest.date().isoformat()}.")
    latest_mfp = (
        db.query(func.max(NormalizedMetric.observed_start))
        .filter(NormalizedMetric.source.ilike("%myfitnesspal%"))
        .scalar()
    )
    if latest_mfp is None:
        warnings.append("MyFitnessPal export data has not been imported yet.")
    elif latest_mfp.date() < date.today() - timedelta(days=7):
        warnings.append(f"MyFitnessPal data is stale after {latest_mfp.date().isoformat()}.")
    return warnings


def optional_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)
