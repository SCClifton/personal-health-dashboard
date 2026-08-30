from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from health_dashboard.models import DoseChangeContext, MedicationDose
from health_dashboard.services.ingestion import rebuild_daily_features, store_raw_event
from health_dashboard.services.normalization import MetricValue


def log_tirzepatide_dose(
    db: Session,
    *,
    dose_mg: float,
    taken_at: datetime,
    side_effects: str | None = None,
    appetite: str | None = None,
    gi_symptoms: str | None = None,
    hydration_notes: str | None = None,
    notes: str | None = None,
) -> MedicationDose:
    stored_taken_at = taken_at.astimezone(timezone.utc) if taken_at.tzinfo else taken_at.replace(tzinfo=timezone.utc)
    dose = MedicationDose(
        medication_name="tirzepatide",
        dose_mg=dose_mg,
        taken_at=stored_taken_at,
        side_effects=side_effects,
        appetite=appetite,
        gi_symptoms=gi_symptoms,
        hydration_notes=hydration_notes,
        notes=notes,
    )
    db.add(dose)
    db.flush()
    payload = {
        "id": dose.id,
        "metric_name": "tirzepatide_dose_mg",
        "value": dose_mg,
        "unit": "mg",
        "observed_start": stored_taken_at.isoformat(),
        "side_effects": side_effects,
        "appetite": appetite,
        "gi_symptoms": gi_symptoms,
        "hydration_notes": hydration_notes,
        "notes": notes,
    }
    store_raw_event(
        db,
        provider="medication",
        payload=payload,
        source_record_id=dose.id,
        metrics=[
            MetricValue(
                metric_name="tirzepatide_dose_mg",
                value_numeric=dose_mg,
                value_text=None,
                unit="mg",
                observed_start=stored_taken_at,
                source="manual",
            )
        ],
    )
    rebuild_daily_features(db)
    return dose


def upsert_dose_change_context(
    db: Session,
    *,
    medication_name: str,
    prior_dose_mg: float | None = None,
    planned_dose_mg: float | None = None,
    planned_start_date: date | None = None,
    clinician_name: str | None = None,
    source_type: str | None = None,
    source_reference: str | None = None,
    preparation_notes: str | None = None,
    monitoring_notes: str | None = None,
    follow_up_questions: str | None = None,
) -> DoseChangeContext:
    existing = db.scalar(
        select(DoseChangeContext).where(
            DoseChangeContext.medication_name == medication_name,
            DoseChangeContext.planned_start_date == planned_start_date,
            DoseChangeContext.planned_dose_mg == planned_dose_mg,
            DoseChangeContext.source_reference == source_reference,
        )
    )
    context = existing or DoseChangeContext(
        medication_name=medication_name,
        planned_start_date=planned_start_date,
        planned_dose_mg=planned_dose_mg,
        source_reference=source_reference,
    )
    context.medication_name = medication_name
    context.prior_dose_mg = prior_dose_mg
    context.planned_dose_mg = planned_dose_mg
    context.planned_start_date = planned_start_date
    context.clinician_name = clinician_name
    context.source_type = source_type
    context.source_reference = source_reference
    context.preparation_notes = preparation_notes
    context.monitoring_notes = monitoring_notes
    context.follow_up_questions = follow_up_questions
    if not existing:
        db.add(context)
    db.flush()
    return context


def latest_dose_change_context(db: Session, *, medication_name: str) -> DoseChangeContext | None:
    return db.scalar(
        select(DoseChangeContext)
        .where(DoseChangeContext.medication_name == medication_name)
        .order_by(DoseChangeContext.planned_start_date.desc(), DoseChangeContext.created_at.desc())
        .limit(1)
    )
