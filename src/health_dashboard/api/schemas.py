from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


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


class StrengthSetIn(BaseModel):
    position: int = Field(gt=0)
    status: Literal["completed", "partial", "skipped"] = "completed"
    reps: int | None = Field(default=None, ge=0)
    rep_multiplier: float = Field(default=1.0, gt=0, le=4)
    load_value: float | None = Field(default=None, ge=0)
    load_unit: Literal["kg", "lb"] | None = None
    load_multiplier: float = Field(default=1.0, gt=0, le=4)
    duration_seconds: float | None = Field(default=None, ge=0)
    distance_meters: float | None = Field(default=None, ge=0)
    rpe: float | None = Field(default=None, ge=1, le=10)
    is_warmup: bool = False
    notes: str | None = None

    @model_validator(mode="after")
    def load_has_value_and_unit(self) -> StrengthSetIn:
        if (self.load_value is None) != (self.load_unit is None):
            raise ValueError("load_value and load_unit must be supplied together")
        return self


class StrengthExerciseIn(BaseModel):
    position: int = Field(gt=0)
    series_name: str | None = None
    name: str = Field(min_length=1, max_length=255)
    status: Literal["completed", "partial", "skipped", "unknown"] = "completed"
    planned_sets: str | None = None
    planned_reps: str | None = None
    planned_tempo: str | None = None
    planned_rest_seconds: float | None = Field(default=None, ge=0)
    target_intensity: str | None = None
    planned_notes: str | None = None
    notes: str | None = None
    sets: list[StrengthSetIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_set_positions(self) -> StrengthExerciseIn:
        positions = [item.position for item in self.sets]
        if len(positions) != len(set(positions)):
            raise ValueError("set positions must be unique within an exercise")
        return self


class StrengthSessionIn(BaseModel):
    source_record_id: str = Field(min_length=1, max_length=255)
    source_kind: Literal["voice", "typed", "import"] = "voice"
    source_text: str | None = None
    capture_status: Literal["complete", "partial"] = "partial"
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, gt=0)
    timezone: str = "Australia/Sydney"
    timing_confidence: Literal["exact", "estimated"] = "estimated"
    program_name: str | None = None
    program_session_name: str | None = None
    program_week: int | None = Field(default=None, ge=1)
    program_block: int | None = Field(default=None, ge=1)
    program_notes: str | None = None
    session_rpe: float | None = Field(default=None, ge=1, le=10)
    notes: str | None = None
    exercises: list[StrengthExerciseIn] = Field(default_factory=list)

    @field_validator("started_at", "ended_at")
    @classmethod
    def timestamps_are_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must include a UTC offset")
        return value

    @field_validator("timezone")
    @classmethod
    def timezone_is_valid(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def session_is_consistent(self) -> StrengthSessionIn:
        if self.source_kind in {"voice", "typed"} and not (self.source_text or "").strip():
            raise ValueError("voice and typed sessions must preserve source_text")
        if self.ended_at is not None and self.ended_at <= self.started_at:
            raise ValueError("ended_at must be after started_at")
        positions = [item.position for item in self.exercises]
        if len(positions) != len(set(positions)):
            raise ValueError("exercise positions must be unique within a session")
        if self.capture_status == "complete" and not any(
            exercise.status in {"completed", "partial"}
            and any(item.status in {"completed", "partial"} for item in exercise.sets)
            for exercise in self.exercises
        ):
            raise ValueError("complete sessions must contain at least one performed set")
        return self
