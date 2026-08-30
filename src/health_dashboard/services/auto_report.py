from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from health_dashboard.config import Settings
from health_dashboard.models import DailyFeature, MedicationDose, NormalizedMetric, OAuthToken, RawEvent
from health_dashboard.services.analytics import metric_snapshot
from health_dashboard.services.coaching import coaching_missing_data_actions, source_freshness
from health_dashboard.services.ingestion import daily_feature_rows, rebuild_daily_features
from health_dashboard.services.oura_sync import sync_oura
from health_dashboard.services.strava_sync import sync_strava
from health_dashboard.services.sync_queue import provider_sync_slot
from health_dashboard.services.time import local_date
from health_dashboard.services.whoop_sync import sync_whoop


CORE_METRICS = [
    "weight",
    "calories",
    "protein",
    "carbs",
    "fat",
    "systolic_bp",
    "diastolic_bp",
    "resting_hr",
    "hrv",
    "sleep_duration",
    "sleep_efficiency",
    "steps",
    "active_energy",
    "training_load",
    "workout_count",
    "tirzepatide_dose_mg",
]

EXTRA_METRICS = [
    "distance",
    "basal_energy_burned",
    "respiratory_rate",
    "blood_oxygen_saturation",
    "breathing_disturbance_index",
    "sleep_score",
    "readiness_score",
    "sleep_average_hr",
    "sleep_lowest_hr",
    "heart_rate",
    "oura_activity_score",
    "oura_stress_high_duration",
    "oura_recovery_high_duration",
    "vascular_age",
    "pulse_wave_velocity",
    "body_fat_percentage",
    "body_mass_index",
    "vo2_max",
    "walking_speed",
    "walking_step_length",
    "walking_asymmetry_percentage",
    "walking_double_support_percentage",
    "time_in_daylight",
    "apple_stand_time",
    "apple_exercise_time",
    "max_heart_rate",
]


async def build_auto_health_report(
    db: Session,
    settings: Settings,
    *,
    days: int = 90,
    sync: bool = True,
    sync_days: int = 14,
    report_date: date | None = None,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc)
    requested_date = report_date or datetime.now(ZoneInfo(settings.local_timezone)).date()
    sync_results = await sync_connected_sources(db, settings, days=sync_days) if sync else []
    rebuild_daily_features(db)
    db.commit()

    rows = daily_feature_rows(db, days=days)
    latest = rows[-1] if rows else None
    freshness = source_freshness(db)
    missing_actions = coaching_missing_data_actions(db, rows)
    report = {
        "generated_at": generated_at.isoformat(),
        "report_date": requested_date.isoformat(),
        "generated_for_days": days,
        "latest_daily_date": latest.date.isoformat() if latest else None,
        "days_since_latest_daily": (requested_date - latest.date).days if latest else None,
        "sync_results": sync_results,
        "source_freshness": freshness,
        "core_metrics": core_metric_snapshot(rows, latest, settings.height_cm),
        "extra_metrics": latest_extra_metrics(db),
        "medication": latest_medication(db, requested_date, settings.local_timezone),
        "missing_data_actions": missing_actions,
    }
    report["facts"] = fact_lines(report)
    report["suggestions"] = suggestion_lines(report)
    return report


async def sync_connected_sources(db: Session, settings: Settings, *, days: int) -> list[dict[str, Any]]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    results: list[dict[str, Any]] = []
    for provider, sync_func in (("whoop", sync_whoop), ("strava", sync_strava), ("oura", sync_oura)):
        auth_detail = provider_auth_detail(db, settings, provider)
        if not auth_detail["can_sync"]:
            results.append({"provider": provider, "status": "skipped", "detail": auth_detail["detail"]})
            continue
        try:
            async with provider_sync_slot(provider):
                result = await sync_func(db, settings, start=start, end=end)
            db.commit()
            results.append(
                {
                    "provider": provider,
                    "status": "synced",
                    "imported": result.get("imported", 0),
                    "duplicates": result.get("duplicates", 0),
                    "detail": sync_result_detail(provider, result),
                }
            )
        except Exception as exc:
            db.rollback()
            results.append({"provider": provider, "status": "failed", "detail": safe_error(exc)})
    results.append({"provider": "apple_health", "status": "checked", "detail": "Push-only source; freshness is reported from local receipts."})
    return results


def provider_auth_detail(db: Session, settings: Settings, provider: str) -> dict[str, Any]:
    token = db.get(OAuthToken, provider)
    if token is not None and token.access_token:
        return {"can_sync": True, "detail": "OAuth token stored."}
    if provider == "oura" and settings.oura_personal_access_token:
        return {"can_sync": True, "detail": "Oura personal access token loaded."}
    if provider == "oura" and settings.oura_client_id and settings.oura_client_secret:
        return {"can_sync": False, "detail": "Oura app credentials are loaded, but no OAuth token is stored. Visit /auth/oura/start or load OURA_PERSONAL_ACCESS_TOKEN."}
    return {"can_sync": False, "detail": "No OAuth token stored."}


def sync_result_detail(provider: str, result: dict[str, Any]) -> str:
    if provider == "strava":
        return f"{result.get('activities', 0)} activities returned."
    collections = result.get("collections")
    if isinstance(collections, dict):
        names = ", ".join(sorted(collections))
        return f"Collections checked: {names}."
    return "Provider sync completed."


def safe_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return text[:240] if text else exc.__class__.__name__


def core_metric_snapshot(rows: list[DailyFeature], latest: DailyFeature | None, height_cm: float | None) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for metric in CORE_METRICS:
        snapshot = metric_snapshot(rows, metric, height_cm)
        snapshots[metric] = {
            "latest": snapshot.latest,
            "latest_date": snapshot.latest_date.isoformat() if snapshot.latest_date else None,
            "average_7d": snapshot.average_7d,
            "average_28d": snapshot.average_28d,
            "delta_28d": snapshot.delta_28d,
            "source": snapshot.source,
            "present_days": snapshot.present_days,
        }
    if latest:
        snapshots["tirzepatide_days_since_dose"] = {
            "latest": latest.tirzepatide_days_since_dose,
            "latest_date": latest.date.isoformat(),
            "average_7d": None,
            "average_28d": None,
            "delta_28d": None,
            "source": None,
            "present_days": sum(1 for row in rows if row.tirzepatide_days_since_dose is not None),
        }
    return snapshots


def latest_extra_metrics(db: Session) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric_name in EXTRA_METRICS:
        metric = db.scalar(
            select(NormalizedMetric)
            .where(NormalizedMetric.metric_name == metric_name, NormalizedMetric.value_numeric.is_not(None))
            .order_by(NormalizedMetric.observed_start.desc(), NormalizedMetric.created_at.desc())
            .limit(1)
        )
        if metric is None:
            continue
        rows.append(
            {
                "metric": metric.metric_name,
                "latest": metric.value_numeric,
                "unit": metric.unit,
                "provider": metric.provider,
                "source": metric.source,
                "observed_start": metric.observed_start.isoformat(),
            }
        )
    return rows


def latest_medication(db: Session, report_date: date, tz_name: str) -> dict[str, Any] | None:
    dose = db.scalar(select(MedicationDose).order_by(MedicationDose.taken_at.desc()).limit(1))
    if dose is None:
        return None
    dose_day = local_date(dose.taken_at, tz_name)
    return {
        "medication_name": dose.medication_name,
        "dose_mg": dose.dose_mg,
        "taken_at": dose.taken_at.isoformat(),
        "days_since_dose_at_report_date": (report_date - dose_day).days,
    }


def fact_lines(report: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    latest_daily = report.get("latest_daily_date")
    if latest_daily:
        stale_days = report.get("days_since_latest_daily")
        facts.append(f"Latest daily feature row is {latest_daily} ({stale_days} day(s) before the report date).")
    else:
        facts.append("No daily feature rows are available yet.")
    for provider in ("whoop", "oura", "apple_health", "strava", "nutrition"):
        freshness = freshness_for(report, provider)
        if freshness:
            facts.append(
                f"{provider}: raw={freshness.get('last_raw_event_at') or '-'}, observed={freshness.get('last_observed_at') or '-'}."
            )
    for metric in ("weight", "calories", "protein", "resting_hr", "hrv", "sleep_duration", "steps", "training_load", "workout_count"):
        item = report["core_metrics"].get(metric) or {}
        if item.get("latest") is not None:
            facts.append(f"{metric}: latest {fmt(item.get('latest'))} on {item.get('latest_date')} from {item.get('source') or '-'}")
    medication = report.get("medication")
    if medication:
        facts.append(
            f"{medication['medication_name']}: latest logged dose {fmt(medication['dose_mg'])} mg on {medication['taken_at']}."
        )
    return facts


def suggestion_lines(report: dict[str, Any]) -> list[str]:
    suggestions: list[str] = []
    if (report.get("days_since_latest_daily") or 0) > 0:
        suggestions.append("Treat today's interpretation as incomplete until fresh daily rows land.")
    for sync_result in report.get("sync_results", []):
        if sync_result.get("status") == "failed":
            suggestions.append(f"Review {sync_result['provider']} sync failure: {sync_result.get('detail')}")
    apple = freshness_for(report, "apple_health")
    if apple and not is_date_current(apple.get("last_raw_event_at"), report["report_date"]):
        suggestions.append("Apple Health is stale; verify the receiver, LAN URL, and Health Auto Export automation before relying on fallback data.")
    suggestions.extend(report.get("missing_data_actions") or [])
    deduped: list[str] = []
    for item in suggestions:
        if item not in deduped:
            deduped.append(item)
    return deduped


def freshness_for(report: dict[str, Any], provider: str) -> dict[str, Any] | None:
    for item in report.get("source_freshness", []):
        if item.get("provider") == provider:
            return item
    return None


def is_date_current(value: str | None, report_date: str) -> bool:
    if not value:
        return False
    return value[:10] >= report_date


def render_auto_health_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Daily Health Check-In",
        "",
        f"Generated: {report['generated_at']}",
        f"Report date: {report['report_date']}",
        f"Window: {report['generated_for_days']} days",
        "",
        "## Sync Results",
    ]
    for item in report.get("sync_results", []):
        counts = ""
        if item.get("imported") is not None:
            counts = f" imported={item.get('imported', 0)}, duplicates={item.get('duplicates', 0)}"
        lines.append(f"- {item['provider']}: {item['status']}{counts}. {item.get('detail', '')}".rstrip())
    lines.extend(["", "## Facts"])
    lines.extend(f"- {item}" for item in report.get("facts", []))
    lines.extend(["", "## Suggestions"])
    suggestions = report.get("suggestions") or ["No immediate missing-data action identified from the local snapshot."]
    lines.extend(f"- {item}" for item in suggestions)
    lines.extend(["", "## Core Metrics"])
    for metric, item in report["core_metrics"].items():
        if item.get("latest") is None:
            continue
        source = item.get("source") or "-"
        lines.append(
            f"- {metric}: latest={fmt(item.get('latest'))}, date={item.get('latest_date')}, 7d={fmt(item.get('average_7d'))}, 28d={fmt(item.get('average_28d'))}, source={source}"
        )
    lines.extend(["", "## Extra Normalized Metrics"])
    extra = report.get("extra_metrics") or []
    if extra:
        for item in extra:
            unit = f" {item['unit']}" if item.get("unit") else ""
            lines.append(
                f"- {item['metric']}: {fmt(item.get('latest'))}{unit} on {item['observed_start']} from {item['provider']} / {item['source']}"
            )
    else:
        lines.append("- No extra normalized metrics available.")
    lines.extend(["", "## Source Freshness"])
    for item in report.get("source_freshness", []):
        lines.append(f"- {item['provider']}: raw={item.get('last_raw_event_at') or '-'}, observed={item.get('last_observed_at') or '-'}")
    lines.extend(
        [
            "",
            "## Boundaries",
            "- Local snapshot only; do not infer missing health facts.",
            "- This report is exploratory and is not medical, dosing, or treatment advice.",
            "- Raw provider payloads, tokens, and secrets are intentionally excluded.",
            "",
        ]
    )
    return "\n".join(lines)


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def raw_event_counts(db: Session) -> dict[str, int]:
    return dict(db.query(RawEvent.provider, func.count(RawEvent.id)).group_by(RawEvent.provider).all())
