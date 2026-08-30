from datetime import date, timedelta

from fastapi.testclient import TestClient

from health_dashboard.api.routes import data_quality_warnings
from health_dashboard.config import Settings, get_settings
from health_dashboard.db import get_db
from health_dashboard.main import app
from health_dashboard.models import DailyFeature
from health_dashboard.services.coaching import (
    adherence_summary,
    build_coaching_snapshot,
    goal_progress,
    upsert_active_goal,
)
from health_dashboard.services.ingestion import rebuild_daily_features, store_raw_event


def feature(day: int, **values) -> DailyFeature:
    return DailyFeature(date=date(2026, 5, day), timezone="Australia/Sydney", source_flags={}, **values)


def test_goal_progress_uses_user_set_target_and_pace(db_session) -> None:
    goal = upsert_active_goal(
        db_session,
        start_date=date(2026, 5, 1),
        target_date=date(2026, 7, 30),
        start_weight_kg=117.0,
        target_weight_kg=102.0,
        daily_calorie_target=1800,
        daily_protein_target_g=160,
    )
    rows = [feature(1, weight=117.0), feature(15, weight=115.0)]

    progress = goal_progress(goal, rows, today=date(2026, 5, 16))

    assert progress.target_loss_kg == 15.0
    assert progress.actual_loss_kg == 2.0
    assert progress.total_days == 90
    assert round(progress.target_weekly_loss_kg, 2) == 1.17
    assert progress.remaining_loss_kg == 13.0


def test_adherence_counts_user_set_calorie_and_protein_targets(db_session) -> None:
    goal = upsert_active_goal(
        db_session,
        start_date=date(2026, 5, 1),
        target_date=date(2026, 7, 30),
        start_weight_kg=117.0,
        target_weight_kg=102.0,
        daily_calorie_target=1800,
        daily_protein_target_g=150,
    )
    rows = [feature(1, calories=1750, protein=151), feature(2, calories=1850, protein=120), feature(3)]

    summary = adherence_summary(rows, goal)

    assert summary.calories_logged_days == 2
    assert summary.protein_logged_days == 2
    assert summary.calorie_target_days == 1
    assert summary.protein_target_days == 1


def test_coach_dashboard_renders_without_saved_goal(db_session) -> None:
    def override_db():
        yield db_session

    def override_settings():
        return Settings(database_url="sqlite://")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    try:
        client = TestClient(app)
        response = client.get("/dashboard/coach")
        assert response.status_code == 200
        assert "Coach" in response.text
        assert "not medical advice" in response.text
    finally:
        app.dependency_overrides.clear()


def test_coaching_snapshot_excludes_raw_payloads_and_lists_actions(db_session) -> None:
    rows = [feature(1, weight=117.0), feature(2, calories=1700)]

    snapshot = build_coaching_snapshot(db_session, rows, days=90)

    assert snapshot.generated_for_days == 90
    assert "raw_events" not in str(snapshot)
    assert snapshot.missing_data_actions


def test_data_quality_warns_for_stale_training_and_missing_mfp(db_session) -> None:
    old_day = date.today() - timedelta(days=10)
    store_raw_event(
        db_session,
        provider="strava",
        payload={"id": "old-strava", "metric_name": "workout_count", "value": 1, "date": f"{old_day.isoformat()}T08:00:00+10:00", "source": "strava"},
    )
    rebuild_daily_features(db_session)
    rows = [feature(1)]

    warnings = data_quality_warnings(db_session, rows)

    assert any("STRAVA data is stale" in warning for warning in warnings)
    assert any("MyFitnessPal" in warning for warning in warnings)
