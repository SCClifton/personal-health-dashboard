from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class TirzepatideDoseIn(BaseModel):
    dose_mg: float = Field(gt=0)
    taken_at: datetime
    side_effects: str | None = None
    appetite: str | None = None
    gi_symptoms: str | None = None
    hydration_notes: str | None = None
    notes: str | None = None


class TirzepatideDoseContextIn(BaseModel):
    prior_dose_mg: float | None = Field(default=None, gt=0)
    planned_dose_mg: float | None = Field(default=None, gt=0)
    planned_start_date: date | None = None
    clinician_name: str | None = None
    source_type: str | None = None
    source_reference: str | None = None
    preparation_notes: str | None = None
    monitoring_notes: str | None = None
    follow_up_questions: str | None = None


class ImportResult(BaseModel):
    provider: str
    imported: int
    duplicates: int
    batch_id: str
