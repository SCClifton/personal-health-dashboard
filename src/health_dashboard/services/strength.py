from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from health_dashboard.api.schemas import StrengthSessionIn, StrengthSetIn
from health_dashboard.models import StrengthExercise, StrengthSession, StrengthSet
from health_dashboard.services.ingestion import store_raw_event
from health_dashboard.services.normalization import MetricValue


LB_TO_KG = 0.45359237
PERFORMED_STATUSES = {"completed", "partial"}


def load_to_kg(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    if unit == "kg":
        return float(value)
    if unit == "lb":
        return float(value) * LB_TO_KG
    raise ValueError(f"unsupported strength load unit: {unit}")


def payload_totals(payload: StrengthSessionIn) -> dict[str, float]:
    performed_sets = [
        item
        for exercise in payload.exercises
        if exercise.status in PERFORMED_STATUSES
        for item in exercise.sets
        if item.status in PERFORMED_STATUSES
    ]
    rep_count = sum((item.reps or 0) * item.rep_multiplier for item in performed_sets)
    volume_load_kg = sum(_set_volume_load_kg(item) for item in performed_sets)
    distance_meters = sum((item.distance_meters or 0) * item.rep_multiplier for item in performed_sets)
    duration_seconds = _session_duration_seconds(payload)
    set_rpes = [item.rpe for item in performed_sets if item.rpe is not None]
    return {
        "set_count": float(len(performed_sets)),
        "rep_count": float(rep_count),
        "volume_load_kg": float(volume_load_kg),
        "distance_meters": float(distance_meters),
        "duration_seconds": float(duration_seconds or 0),
        "average_set_rpe": float(mean(set_rpes)) if set_rpes else 0.0,
    }


def metrics_from_strength_session(payload: StrengthSessionIn) -> list[MetricValue]:
    totals = payload_totals(payload)
    observed_start = payload.started_at.astimezone(timezone.utc)
    observed_end = payload.ended_at.astimezone(timezone.utc) if payload.ended_at else None
    metric_values = [
        ("strength_session_count", 1.0, "count"),
        ("strength_set_count", totals["set_count"], "count"),
        ("strength_rep_count", totals["rep_count"], "count"),
        ("strength_volume_load", totals["volume_load_kg"], "kg-reps"),
    ]
    if totals["duration_seconds"]:
        metric_values.append(("strength_duration", totals["duration_seconds"] / 3600, "h"))
    if totals["distance_meters"]:
        metric_values.append(("strength_distance", totals["distance_meters"], "m"))
    if payload.session_rpe is not None:
        metric_values.append(("strength_session_rpe", payload.session_rpe, "rpe"))
    elif totals["average_set_rpe"]:
        metric_values.append(("strength_session_rpe", totals["average_set_rpe"], "rpe"))
    confidence = 1.0 if payload.capture_status == "complete" else 0.8
    return [
        MetricValue(
            metric_name=name,
            value_numeric=value,
            value_text=None,
            unit=unit,
            observed_start=observed_start,
            observed_end=observed_end,
            aggregation_window="event",
            confidence=confidence,
            source="manual_strength",
        )
        for name, value, unit in metric_values
    ]


def import_strength_session(db: Session, payload: StrengthSessionIn) -> tuple[StrengthSession, bool]:
    raw_payload = payload.model_dump(mode="json")
    raw_event, created = store_raw_event(
        db,
        provider="manual_strength",
        payload=raw_payload,
        source_record_id=payload.source_record_id,
        permissions_scope="local_strength_session",
        schema_version="strength_session.v1",
        metrics=metrics_from_strength_session(payload),
    )
    existing = db.scalar(
        select(StrengthSession)
        .where(StrengthSession.source == "manual_strength", StrengthSession.source_record_id == payload.source_record_id)
        .options(selectinload(StrengthSession.exercises).selectinload(StrengthExercise.sets))
    )
    if existing:
        return existing, False

    session = StrengthSession(
        raw_event_id=raw_event.id,
        source="manual_strength",
        source_record_id=payload.source_record_id,
        source_kind=payload.source_kind,
        capture_status=payload.capture_status,
        started_at=payload.started_at.astimezone(timezone.utc),
        ended_at=payload.ended_at.astimezone(timezone.utc) if payload.ended_at else None,
        duration_seconds=_session_duration_seconds(payload),
        timezone=payload.timezone,
        timing_confidence=payload.timing_confidence,
        program_name=payload.program_name,
        program_session_name=payload.program_session_name,
        program_week=payload.program_week,
        program_block=payload.program_block,
        program_notes=payload.program_notes,
        session_rpe=payload.session_rpe,
        notes=payload.notes,
    )
    for exercise_payload in payload.exercises:
        exercise = StrengthExercise(
            position=exercise_payload.position,
            series_name=exercise_payload.series_name,
            name=exercise_payload.name,
            status=exercise_payload.status,
            planned_sets=exercise_payload.planned_sets,
            planned_reps=exercise_payload.planned_reps,
            planned_tempo=exercise_payload.planned_tempo,
            planned_rest_seconds=exercise_payload.planned_rest_seconds,
            target_intensity=exercise_payload.target_intensity,
            planned_notes=exercise_payload.planned_notes,
            notes=exercise_payload.notes,
        )
        for set_payload in exercise_payload.sets:
            exercise.sets.append(
                StrengthSet(
                    position=set_payload.position,
                    status=set_payload.status,
                    reps=set_payload.reps,
                    rep_multiplier=set_payload.rep_multiplier,
                    load_value=set_payload.load_value,
                    load_unit=set_payload.load_unit,
                    load_kg=load_to_kg(set_payload.load_value, set_payload.load_unit),
                    load_multiplier=set_payload.load_multiplier,
                    duration_seconds=set_payload.duration_seconds,
                    distance_meters=set_payload.distance_meters,
                    rpe=set_payload.rpe,
                    is_warmup=set_payload.is_warmup,
                    notes=set_payload.notes,
                )
            )
        session.exercises.append(exercise)
    db.add(session)
    db.flush()
    return session, created


def recent_strength_sessions(db: Session, *, days: int = 90, limit: int = 100) -> list[StrengthSession]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return list(
        db.scalars(
            select(StrengthSession)
            .where(StrengthSession.started_at >= cutoff)
            .options(selectinload(StrengthSession.exercises).selectinload(StrengthExercise.sets))
            .order_by(StrengthSession.started_at.desc())
            .limit(limit)
        )
    )


def serialize_strength_session(session: StrengthSession) -> dict[str, Any]:
    performed_sets = [
        item
        for exercise in session.exercises
        if exercise.status in PERFORMED_STATUSES
        for item in exercise.sets
        if item.status in PERFORMED_STATUSES
    ]
    rep_count = sum((item.reps or 0) * item.rep_multiplier for item in performed_sets)
    volume_load_kg = sum(
        (item.load_kg or 0) * (item.reps or 0) * item.rep_multiplier * item.load_multiplier for item in performed_sets
    )
    distance_meters = sum((item.distance_meters or 0) * item.rep_multiplier for item in performed_sets)
    set_rpes = [item.rpe for item in performed_sets if item.rpe is not None]
    return {
        "id": session.id,
        "source": session.source,
        "source_record_id": session.source_record_id,
        "source_kind": session.source_kind,
        "capture_status": session.capture_status,
        "started_at": _iso_utc(session.started_at),
        "ended_at": _iso_utc(session.ended_at),
        "duration_seconds": session.duration_seconds,
        "timezone": session.timezone,
        "timing_confidence": session.timing_confidence,
        "program_name": session.program_name,
        "program_session_name": session.program_session_name,
        "program_week": session.program_week,
        "program_block": session.program_block,
        "program_notes": session.program_notes,
        "session_rpe": session.session_rpe,
        "notes": session.notes,
        "totals": {
            "set_count": len(performed_sets),
            "rep_count": rep_count,
            "volume_load_kg": volume_load_kg,
            "distance_meters": distance_meters,
            "duration_seconds": session.duration_seconds or 0,
            "average_set_rpe": float(mean(set_rpes)) if set_rpes else 0.0,
        },
        "exercises": [
            {
                "position": exercise.position,
                "series_name": exercise.series_name,
                "name": exercise.name,
                "status": exercise.status,
                "planned_sets": exercise.planned_sets,
                "planned_reps": exercise.planned_reps,
                "planned_tempo": exercise.planned_tempo,
                "planned_rest_seconds": exercise.planned_rest_seconds,
                "target_intensity": exercise.target_intensity,
                "planned_notes": exercise.planned_notes,
                "notes": exercise.notes,
                "sets": [
                    {
                        "position": item.position,
                        "status": item.status,
                        "reps": item.reps,
                        "rep_multiplier": item.rep_multiplier,
                        "load_value": item.load_value,
                        "load_unit": item.load_unit,
                        "load_kg": item.load_kg,
                        "load_multiplier": item.load_multiplier,
                        "duration_seconds": item.duration_seconds,
                        "distance_meters": item.distance_meters,
                        "rpe": item.rpe,
                        "is_warmup": item.is_warmup,
                        "notes": item.notes,
                    }
                    for item in exercise.sets
                ],
            }
            for exercise in session.exercises
        ],
    }


def _set_volume_load_kg(item: StrengthSetIn) -> float:
    load_kg = load_to_kg(item.load_value, item.load_unit)
    if load_kg is None or item.reps is None:
        return 0.0
    return load_kg * item.reps * item.rep_multiplier * item.load_multiplier


def _session_duration_seconds(payload: StrengthSessionIn) -> float | None:
    if payload.duration_seconds is not None:
        return payload.duration_seconds
    if payload.ended_at is not None:
        return (payload.ended_at - payload.started_at).total_seconds()
    return None


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
