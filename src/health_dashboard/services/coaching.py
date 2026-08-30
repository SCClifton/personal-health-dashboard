from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from statistics import mean

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from health_dashboard.models import CoachingGoal, DailyFeature, NormalizedMetric, RawEvent
from health_dashboard.services.analytics import metric_snapshot


DEFAULT_TARGET_LOSS_KG = 15.0


@dataclass(frozen=True)
class GoalProgress:
    goal: CoachingGoal | None
    latest_weight_kg: float | None
    latest_weight_date: date | None
    target_loss_kg: float | None
    actual_loss_kg: float | None
    expected_loss_kg: float | None
    remaining_loss_kg: float | None
    total_days: int | None
    elapsed_days: int | None
    remaining_days: int | None
    target_weekly_loss_kg: float | None
    actual_weekly_loss_kg: float | None
    on_track_delta_kg: float | None


@dataclass(frozen=True)
class AdherenceSummary:
    calories_logged_days: int
    protein_logged_days: int
    calorie_target_days: int
    protein_target_days: int
    average_calories: float | None
    average_protein_g: float | None
    latest_calories: float | None
    latest_protein_g: float | None


@dataclass(frozen=True)
class CoachingSnapshot:
    generated_for_days: int
    goal: dict
    adherence: dict
    training_sleep: dict
    source_freshness: list[dict]
    missing_data_actions: list[str]


def active_goal(db: Session) -> CoachingGoal | None:
    return db.scalar(select(CoachingGoal).where(CoachingGoal.is_active == 1).order_by(CoachingGoal.updated_at.desc()))


def upsert_active_goal(
    db: Session,
    *,
    start_date: date,
    target_date: date,
    start_weight_kg: float,
    target_weight_kg: float | None = None,
    target_loss_kg: float = DEFAULT_TARGET_LOSS_KG,
    daily_calorie_target: float | None = None,
    daily_protein_target_g: float | None = None,
    notes: str | None = None,
) -> CoachingGoal:
    goal = active_goal(db)
    if goal is None:
        goal = CoachingGoal(start_date=start_date, target_date=target_date, start_weight_kg=start_weight_kg, target_weight_kg=start_weight_kg - target_loss_kg)
        db.add(goal)
    goal.name = "Weight loss"
    goal.is_active = 1
    goal.start_date = start_date
    goal.target_date = target_date
    goal.start_weight_kg = start_weight_kg
    goal.target_weight_kg = target_weight_kg if target_weight_kg is not None else start_weight_kg - target_loss_kg
    goal.daily_calorie_target = daily_calorie_target
    goal.daily_protein_target_g = daily_protein_target_g
    goal.notes = notes
    db.flush()
    return goal


def default_goal_from_rows(rows: list[DailyFeature], today: date | None = None) -> CoachingGoal | None:
    weights = [(row.date, row.weight) for row in rows if row.weight is not None]
    if not weights:
        return None
    start_day, start_weight = weights[-1]
    target = today or date.today()
    transient = CoachingGoal(
        id="default",
        name="Weight loss",
        is_active=1,
        start_date=start_day,
        target_date=target + timedelta(days=90),
        start_weight_kg=float(start_weight),
        target_weight_kg=float(start_weight) - DEFAULT_TARGET_LOSS_KG,
    )
    return transient


def goal_progress(goal: CoachingGoal | None, rows: list[DailyFeature], today: date | None = None) -> GoalProgress:
    today = today or date.today()
    weights = [(row.date, row.weight) for row in rows if row.weight is not None]
    latest_date, latest_weight = weights[-1] if weights else (None, None)
    if goal is None:
        return GoalProgress(goal, latest_weight, latest_date, None, None, None, None, None, None, None, None, None, None)

    total_days = max((goal.target_date - goal.start_date).days, 1)
    elapsed_days = min(max((today - goal.start_date).days, 0), total_days)
    remaining_days = max((goal.target_date - today).days, 0)
    target_loss = goal.start_weight_kg - goal.target_weight_kg
    actual_loss = goal.start_weight_kg - latest_weight if latest_weight is not None else None
    expected_loss = target_loss * (elapsed_days / total_days)
    remaining_loss = latest_weight - goal.target_weight_kg if latest_weight is not None else None
    target_weekly = target_loss / total_days * 7
    actual_weekly = actual_loss / max(elapsed_days, 1) * 7 if actual_loss is not None and elapsed_days > 0 else None
    on_track = actual_loss - expected_loss if actual_loss is not None else None
    return GoalProgress(
        goal=goal,
        latest_weight_kg=latest_weight,
        latest_weight_date=latest_date,
        target_loss_kg=target_loss,
        actual_loss_kg=actual_loss,
        expected_loss_kg=expected_loss,
        remaining_loss_kg=remaining_loss,
        total_days=total_days,
        elapsed_days=elapsed_days,
        remaining_days=remaining_days,
        target_weekly_loss_kg=target_weekly,
        actual_weekly_loss_kg=actual_weekly,
        on_track_delta_kg=on_track,
    )


def adherence_summary(rows: list[DailyFeature], goal: CoachingGoal | None, days: int = 28) -> AdherenceSummary:
    recent = rows[-days:]
    calorie_values = [row.calories for row in recent if row.calories is not None]
    protein_values = [row.protein for row in recent if row.protein is not None]
    calorie_target = goal.daily_calorie_target if goal else None
    protein_target = goal.daily_protein_target_g if goal else None
    return AdherenceSummary(
        calories_logged_days=len(calorie_values),
        protein_logged_days=len(protein_values),
        calorie_target_days=sum(1 for value in calorie_values if calorie_target is not None and value <= calorie_target),
        protein_target_days=sum(1 for value in protein_values if protein_target is not None and value >= protein_target),
        average_calories=mean(calorie_values) if calorie_values else None,
        average_protein_g=mean(protein_values) if protein_values else None,
        latest_calories=calorie_values[-1] if calorie_values else None,
        latest_protein_g=protein_values[-1] if protein_values else None,
    )


def source_freshness(db: Session) -> list[dict]:
    raw_rows = dict(db.query(RawEvent.provider, func.max(RawEvent.received_at)).group_by(RawEvent.provider).all())
    metric_rows = dict(db.query(NormalizedMetric.provider, func.max(NormalizedMetric.observed_start)).group_by(NormalizedMetric.provider).all())
    providers = sorted(set(raw_rows) | set(metric_rows) | {"apple_health", "whoop", "strava", "nutrition", "hybrd"})
    return [
        {
            "provider": provider,
            "last_raw_event_at": raw_rows.get(provider).isoformat() if raw_rows.get(provider) else None,
            "last_observed_at": metric_rows.get(provider).isoformat() if metric_rows.get(provider) else None,
        }
        for provider in providers
    ]


def coaching_missing_data_actions(db: Session, rows: list[DailyFeature]) -> list[str]:
    actions: list[str] = []
    recent = rows[-30:]
    if sum(1 for row in recent if row.calories is not None) < 21:
        actions.append("Import a recent MyFitnessPal export so calorie adherence is based on logged food, not estimates.")
    if sum(1 for row in recent if row.protein is not None) < 21:
        actions.append("Keep protein logged in MyFitnessPal; protein target adherence needs most days populated.")
    if sum(1 for row in recent if row.weight is not None) < 14:
        actions.append("Add more weigh-ins or scale syncs; the weight trend is sparse for a three-month target.")
    if not any(row.systolic_bp is not None or row.diastolic_bp is not None for row in recent):
        actions.append("Blood pressure is absent; sync Hilo/Apple Health or import cuff readings before drawing BP trend conclusions.")
    latest_daily = rows[-1].date if rows else None
    if latest_daily and latest_daily < date.today() - timedelta(days=2):
        actions.append(f"Daily features are stale after {latest_daily.isoformat()}; run sync/import and rebuild daily features.")
    for provider in ("apple_health", "whoop", "strava"):
        latest = db.query(func.max(NormalizedMetric.observed_start)).filter(NormalizedMetric.provider == provider).scalar()
        if latest is None:
            actions.append(f"{provider} has no normalized metrics yet.")
        elif latest.date() < date.today() - timedelta(days=2):
            actions.append(f"{provider} observed data is stale after {latest.date().isoformat()}.")
    return actions


def build_coaching_snapshot(db: Session, rows: list[DailyFeature], days: int = 90) -> CoachingSnapshot:
    rows = rows[-days:]
    goal = active_goal(db) or default_goal_from_rows(rows)
    progress = goal_progress(goal, rows)
    adherence = adherence_summary(rows, goal)
    training_sleep = {
        "weight": asdict(metric_snapshot(rows, "weight")),
        "calories": asdict(metric_snapshot(rows, "calories")),
        "protein": asdict(metric_snapshot(rows, "protein")),
        "training_load": asdict(metric_snapshot(rows, "training_load")),
        "workout_count": asdict(metric_snapshot(rows, "workout_count")),
        "sleep_duration": asdict(metric_snapshot(rows, "sleep_duration")),
        "hrv": asdict(metric_snapshot(rows, "hrv")),
        "resting_hr": asdict(metric_snapshot(rows, "resting_hr")),
    }
    return CoachingSnapshot(
        generated_for_days=days,
        goal=serializable_goal_progress(progress),
        adherence=asdict(adherence),
        training_sleep=training_sleep,
        source_freshness=source_freshness(db),
        missing_data_actions=coaching_missing_data_actions(db, rows),
    )


def serializable_goal_progress(progress: GoalProgress) -> dict:
    data = {
        "goal": None,
        "latest_weight_kg": progress.latest_weight_kg,
        "latest_weight_date": progress.latest_weight_date.isoformat() if progress.latest_weight_date else None,
        "target_loss_kg": progress.target_loss_kg,
        "actual_loss_kg": progress.actual_loss_kg,
        "expected_loss_kg": progress.expected_loss_kg,
        "remaining_loss_kg": progress.remaining_loss_kg,
        "total_days": progress.total_days,
        "elapsed_days": progress.elapsed_days,
        "remaining_days": progress.remaining_days,
        "target_weekly_loss_kg": progress.target_weekly_loss_kg,
        "actual_weekly_loss_kg": progress.actual_weekly_loss_kg,
        "on_track_delta_kg": progress.on_track_delta_kg,
    }
    goal = progress.goal
    data["goal"] = (
        {
            "id": goal.id,
            "name": goal.name,
            "start_date": goal.start_date.isoformat(),
            "target_date": goal.target_date.isoformat(),
            "start_weight_kg": goal.start_weight_kg,
            "target_weight_kg": goal.target_weight_kg,
            "daily_calorie_target": goal.daily_calorie_target,
            "daily_protein_target_g": goal.daily_protein_target_g,
            "notes": goal.notes,
        }
        if goal
        else None
    )
    return data
