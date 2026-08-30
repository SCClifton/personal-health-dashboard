from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from health_dashboard.config import Settings, get_settings
from health_dashboard.db import get_db
from health_dashboard.main import app
from health_dashboard.models import DailyFeature, DoseChangeContext
from health_dashboard.services.medication import (
    latest_dose_change_context,
    log_tirzepatide_dose,
    upsert_dose_change_context,
)
from health_dashboard.services.time import local_date


def test_dose_change_context_upsert_is_idempotent(db_session) -> None:
    first = upsert_dose_change_context(
        db_session,
        medication_name="tirzepatide",
        prior_dose_mg=2.5,
        planned_dose_mg=5.0,
        planned_start_date=date(2026, 6, 19),
        clinician_name="Vanessa Alimin",
        source_type="transcript",
        source_reference="20260608 transcript",
        preparation_notes="Initial notes",
    )
    second = upsert_dose_change_context(
        db_session,
        medication_name="tirzepatide",
        prior_dose_mg=2.5,
        planned_dose_mg=5.0,
        planned_start_date=date(2026, 6, 19),
        clinician_name="Vanessa Alimin",
        source_type="transcript",
        source_reference="20260608 transcript",
        preparation_notes="Updated notes",
    )
    db_session.commit()

    latest = latest_dose_change_context(db_session, medication_name="tirzepatide")

    assert first.id == second.id
    assert db_session.query(DoseChangeContext).count() == 1
    assert latest is not None
    assert latest.preparation_notes == "Updated notes"


def test_glp1_dashboard_renders_without_dose_context(db_session) -> None:
    def override_db():
        yield db_session

    def override_settings():
        return Settings(database_url="sqlite://", height_cm=180)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    try:
        client = TestClient(app)
        response = client.get("/dashboard/glp1")

        assert response.status_code == 200
        assert "GLP-1 Response" in response.text
        assert "No GLP-1 dose-change context recorded yet" in response.text
    finally:
        app.dependency_overrides.clear()


def test_tirzepatide_dose_context_api_updates_glp1_dashboard(db_session) -> None:
    def override_db():
        yield db_session

    def override_settings():
        return Settings(database_url="sqlite://", height_cm=180)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    try:
        client = TestClient(app)
        payload = {
            "prior_dose_mg": 2.5,
            "planned_dose_mg": 5.0,
            "planned_start_date": "2026-06-19",
            "clinician_name": "Vanessa Alimin",
            "source_type": "transcript",
            "source_reference": "20260608 GLP-1 Strategy Kick Off transcript",
            "preparation_notes": "Protein, fibre, hydration, and movement context.",
            "monitoring_notes": "Monitor appetite, GI symptoms, hydration, BP, HRV, sleep, and training.",
            "follow_up_questions": "Confirm delivery and six-month DEXA/pathology timing.",
        }
        db_session.add(
            DailyFeature(
                date=date(2026, 6, 10),
                timezone="Australia/Sydney",
                weight=116.0,
                source_flags={"weight": ["manual"]},
            )
        )
        db_session.commit()

        created = client.post("/medication/tirzepatide/dose-context", json=payload)
        dashboard = client.get("/dashboard/glp1")

        assert created.status_code == 200
        assert created.json()["planned_start_date"] == "2026-06-19"
        assert dashboard.status_code == 200
        assert "Dose-Change Context" in dashboard.text
        assert "2.5 mg to 5.0 mg" in dashboard.text
        assert "Vanessa Alimin" in dashboard.text
        assert "Planned context is kept separate from actual dose administrations" in dashboard.text
    finally:
        app.dependency_overrides.clear()


def test_local_date_attributes_to_sydney_calendar_day() -> None:
    # 14:30 UTC is 00:30 the next day in AEST (UTC+10, no DST in June).
    instant = datetime(2026, 6, 18, 14, 30, tzinfo=timezone.utc)

    assert local_date(instant, "Australia/Sydney") == date(2026, 6, 19)


def test_dose_logged_across_sydney_midnight_lands_on_local_day(db_session) -> None:
    # 00:30 AEST on 2026-06-19 == 2026-06-18T14:30Z. The dose must be attributed to the
    # Sydney calendar day (2026-06-19), not the UTC day (2026-06-18).
    taken_at = datetime(2026, 6, 19, 0, 30, tzinfo=ZoneInfo("Australia/Sydney"))

    log_tirzepatide_dose(db_session, dose_mg=5.0, taken_at=taken_at)
    db_session.commit()

    feature = db_session.get(
        DailyFeature, {"date": date(2026, 6, 19), "timezone": "Australia/Sydney"}
    )
    assert feature is not None
    assert feature.tirzepatide_dose_mg == 5.0

    earlier = db_session.get(
        DailyFeature, {"date": date(2026, 6, 18), "timezone": "Australia/Sydney"}
    )
    assert earlier is None
