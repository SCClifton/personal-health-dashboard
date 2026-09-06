from datetime import date, datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from health_dashboard.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class RawEvent(Base):
    __tablename__ = "raw_events"
    __table_args__ = (
        UniqueConstraint("provider", "source_record_id", name="uq_raw_provider_source_record"),
        Index("ix_raw_provider_hash", "provider", "payload_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    source_record_id: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    import_batch_id: Mapped[str] = mapped_column(String(36), index=True)
    observed_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    observed_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    permissions_scope: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    schema_version: Mapped[str] = mapped_column(String(32), default="1")

    metrics: Mapped[list["NormalizedMetric"]] = relationship(back_populates="raw_event", cascade="all, delete-orphan")


class NormalizedMetric(Base):
    __tablename__ = "normalized_metrics"
    __table_args__ = (
        Index("ix_metric_lookup", "metric_name", "observed_start", "provider", "source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(128), index=True)
    metric_name: Mapped[str] = mapped_column(String(128), index=True)
    value_numeric: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    observed_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    observed_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    aggregation_window: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    raw_event_id: Mapped[str] = mapped_column(ForeignKey("raw_events.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    raw_event: Mapped[RawEvent] = relationship(back_populates="metrics")


class DailyFeature(Base):
    __tablename__ = "daily_features"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    timezone: Mapped[str] = mapped_column(String(64), primary_key=True)
    weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    calories: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    protein: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    carbs: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    systolic_bp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    diastolic_bp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    resting_hr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hrv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sleep_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sleep_efficiency: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    steps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    active_energy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    training_load: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    workout_count: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tirzepatide_dose_mg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tirzepatide_days_since_dose: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_flags: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CoachingGoal(Base):
    __tablename__ = "coaching_goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), default="Weight loss")
    is_active: Mapped[int] = mapped_column(Integer, default=1, index=True)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    start_weight_kg: Mapped[float] = mapped_column(Float)
    target_weight_kg: Mapped[float] = mapped_column(Float)
    daily_calorie_target: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    daily_protein_target_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ConnectorState(Base):
    __tablename__ = "connector_states"

    connector: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    detail: Mapped[str] = mapped_column(Text)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_action: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MedicationDose(Base):
    __tablename__ = "medication_doses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    medication_name: Mapped[str] = mapped_column(String(128), index=True)
    dose_mg: Mapped[float] = mapped_column(Float)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    side_effects: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    appetite: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    gi_symptoms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hydration_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DoseChangeContext(Base):
    __tablename__ = "dose_change_contexts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    medication_name: Mapped[str] = mapped_column(String(128), index=True)
    prior_dose_mg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    planned_dose_mg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    planned_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    clinician_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preparation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    monitoring_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    follow_up_questions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StrengthSession(Base):
    __tablename__ = "strength_sessions"
    __table_args__ = (
        UniqueConstraint("source", "source_record_id", name="uq_strength_session_source_record"),
        Index("ix_strength_session_started_source", "started_at", "source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    raw_event_id: Mapped[str] = mapped_column(ForeignKey("raw_events.id"), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(64), default="manual_strength", index=True)
    source_record_id: Mapped[str] = mapped_column(String(255), index=True)
    source_kind: Mapped[str] = mapped_column(String(32), default="voice")
    capture_status: Mapped[str] = mapped_column(String(32), default="partial", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64))
    timing_confidence: Mapped[str] = mapped_column(String(32), default="estimated")
    program_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    program_session_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    program_week: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    program_block: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    program_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    session_rpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    exercises: Mapped[list["StrengthExercise"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="StrengthExercise.position",
    )


class StrengthExercise(Base):
    __tablename__ = "strength_exercises"
    __table_args__ = (UniqueConstraint("session_id", "position", name="uq_strength_exercise_position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("strength_sessions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    series_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    planned_sets: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    planned_reps: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    planned_tempo: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    planned_rest_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_intensity: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    planned_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    session: Mapped[StrengthSession] = relationship(back_populates="exercises")
    sets: Mapped[list["StrengthSet"]] = relationship(
        back_populates="exercise",
        cascade="all, delete-orphan",
        order_by="StrengthSet.position",
    )


class StrengthSet(Base):
    __tablename__ = "strength_sets"
    __table_args__ = (UniqueConstraint("exercise_id", "position", name="uq_strength_set_position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("strength_exercises.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    reps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rep_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    load_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    load_unit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    load_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    load_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    distance_meters: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_warmup: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    exercise: Mapped[StrengthExercise] = relationship(back_populates="sets")
