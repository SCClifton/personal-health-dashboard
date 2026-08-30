from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from health_dashboard.config import Settings, get_settings
from health_dashboard.db import get_db
from health_dashboard.main import app
from health_dashboard.models import DailyFeature, NormalizedMetric, RawEvent
from health_dashboard.services.ingestion import store_raw_event
from health_dashboard.services.strava_sync import (
    source_record_id_for_strava_activity,
    source_record_id_for_strava_activity_detail,
    source_record_id_for_strava_activity_laps,
    source_record_id_for_strava_activity_streams,
)


def test_dashboard_renders_without_integrations(db_session) -> None:
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        assert "Overview" in response.text
        assert "No data imported yet" in response.text
    finally:
        app.dependency_overrides.clear()


def test_runs_dashboard_renders_without_recent_runs(db_session) -> None:
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get("/dashboard/runs")
        assert response.status_code == 200
        assert "Run Recovery" in response.text
        assert "No recent Strava runs" in response.text
    finally:
        app.dependency_overrides.clear()


def test_run_recovery_api_and_dashboard_use_stored_strava_detail(db_session) -> None:
    seed_api_strava_run(db_session)

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        recent = client.get("/api/runs/recent?days=14")
        recovery = client.get("/api/runs/321/recovery")
        dashboard = client.get("/dashboard/runs")

        assert recent.status_code == 200
        assert recent.json()[0]["activity_id"] == "321"
        assert recent.json()[0]["has_laps"] is True
        assert recovery.status_code == 200
        assert recovery.json()["repeat_count"] == 4
        assert recovery.json()["confidence"] == "high"
        assert dashboard.status_code == 200
        assert "Detected 400 m Repeats" in dashboard.text
        assert "400 m repeat session" in dashboard.text
    finally:
        app.dependency_overrides.clear()


def test_apple_health_ingest_secret_and_duplicate(db_session, monkeypatch) -> None:
    rebuild_calls = []

    def fake_rebuild(db, start=None, end=None):
        rebuild_calls.append((start, end))

    monkeypatch.setattr("health_dashboard.api.routes.rebuild_daily_features", fake_rebuild)

    def override_db():
        yield db_session

    def override_settings():
        return Settings(database_url="sqlite://", health_auto_export_shared_secret="test-secret")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    try:
        client = TestClient(app)
        payload = {"data": [{"id": "steps-1", "metric_name": "steps", "value": 1000, "unit": "count", "date": "2026-05-03T08:00:00+10:00"}]}
        response = client.post("/ingest/apple-health", json=payload, headers={"Authorization": "Bearer test-secret"})
        duplicate = client.post("/ingest/apple-health", json=payload, headers={"Authorization": "Bearer test-secret"})

        assert response.status_code == 200
        assert response.json()["imported"] == 1
        assert duplicate.status_code == 200
        assert duplicate.json()["duplicates"] == 1
        assert len(rebuild_calls) == 1
        assert str(rebuild_calls[0][0]) == "2026-05-03"
        assert str(rebuild_calls[0][1]) == "2026-05-03"
    finally:
        app.dependency_overrides.clear()


def test_apple_health_empty_ingest_skips_rebuild(db_session, monkeypatch) -> None:
    rebuild_calls = []

    def fake_rebuild(db, start=None, end=None):
        rebuild_calls.append((start, end))

    monkeypatch.setattr("health_dashboard.api.routes.rebuild_daily_features", fake_rebuild)

    def override_db():
        yield db_session

    def override_settings():
        return Settings(database_url="sqlite://", health_auto_export_shared_secret="test-secret")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    try:
        client = TestClient(app)
        response = client.post("/ingest/apple-health", json=[], headers={"Authorization": "Bearer test-secret"})

        assert response.status_code == 200
        assert response.json()["imported"] == 0
        assert response.json()["duplicates"] == 0
        assert rebuild_calls == []
    finally:
        app.dependency_overrides.clear()


def test_apple_health_verify_secret_does_not_import(db_session) -> None:
    def override_db():
        yield db_session

    def override_settings():
        return Settings(database_url="sqlite://", health_auto_export_shared_secret="test-secret")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    try:
        client = TestClient(app)
        ok = client.get("/ingest/apple-health/verify", headers={"Authorization": "Bearer test-secret"})
        unauthorized = client.get("/ingest/apple-health/verify", headers={"Authorization": "Bearer wrong"})

        assert ok.status_code == 200
        assert ok.json() == {"ok": True, "provider": "apple_health"}
        assert unauthorized.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_apple_health_v2_metric_points_are_idempotent(db_session) -> None:
    def override_db():
        yield db_session

    def override_settings():
        return Settings(database_url="sqlite://", health_auto_export_shared_secret="test-secret")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    try:
        client = TestClient(app)
        payload = {
            "data": {
                "metrics": [
                    {
                        "name": "step_count",
                        "units": "count",
                        "data": [
                            {"source": "Apple Watch", "qty": 1000, "date": "2026-06-01 00:00:00 +1000"},
                            {"source": "iPhone", "qty": 500, "date": "2026-06-01 00:00:00 +1000"},
                        ],
                    }
                ]
            }
        }

        first = client.post("/ingest/apple-health", json=payload, headers={"Authorization": "Bearer test-secret"})
        second = client.post("/ingest/apple-health", json=payload, headers={"Authorization": "Bearer test-secret"})

        assert first.status_code == 200
        assert first.json()["imported"] == 2
        assert second.status_code == 200
        assert second.json()["imported"] == 0
        assert second.json()["duplicates"] == 2
        assert db_session.query(RawEvent).filter(RawEvent.provider == "apple_health").count() == 2
        assert db_session.query(NormalizedMetric).filter(NormalizedMetric.metric_name == "steps").count() == 2
    finally:
        app.dependency_overrides.clear()


def test_apple_health_updated_daily_aggregate_keeps_latest_revision(db_session) -> None:
    def override_db():
        yield db_session

    def override_settings():
        return Settings(
            database_url="sqlite://",
            health_auto_export_shared_secret="test-secret",
            local_timezone="Australia/Sydney",
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    try:
        client = TestClient(app)
        first_payload = {
            "data": {
                "metrics": [
                    {
                        "name": "step_count",
                        "units": "count",
                        "data": [{"source": "Apple Watch", "qty": 1000, "date": "2026-06-01 00:00:00 +1000"}],
                    }
                ]
            }
        }
        updated_payload = {
            "data": {
                "metrics": [
                    {
                        "name": "step_count",
                        "units": "count",
                        "data": [{"source": "Apple Watch", "qty": 1500, "date": "2026-06-01 00:00:00 +1000"}],
                    }
                ]
            }
        }

        first = client.post("/ingest/apple-health", json=first_payload, headers={"Authorization": "Bearer test-secret"})
        updated = client.post("/ingest/apple-health", json=updated_payload, headers={"Authorization": "Bearer test-secret"})

        assert first.status_code == 200
        assert first.json()["imported"] == 1
        assert updated.status_code == 200
        assert updated.json()["imported"] == 1

        feature = db_session.get(DailyFeature, {"date": date(2026, 6, 1), "timezone": "Australia/Sydney"})
        assert feature is not None
        assert feature.steps == 1500
    finally:
        app.dependency_overrides.clear()


def test_apple_health_v2_complex_daily_aggregates_are_normalized(db_session) -> None:
    def override_db():
        yield db_session

    def override_settings():
        return Settings(database_url="sqlite://", health_auto_export_shared_secret="test-secret")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    try:
        client = TestClient(app)
        payload = {
            "data": {
                "metrics": [
                    {
                        "name": "blood_pressure",
                        "units": "mmHg",
                        "data": [
                            {
                                "source": "Apple Health",
                                "systolic": 121,
                                "diastolic": 78,
                                "date": "2026-08-29 00:00:00 +1000",
                            }
                        ],
                    },
                    {
                        "name": "heart_rate",
                        "units": "count/min",
                        "data": [
                            {
                                "source": "Apple Watch",
                                "Min": 45,
                                "Avg": 69.5,
                                "Max": 151,
                                "date": "2026-08-29 00:00:00 +1000",
                            }
                        ],
                    },
                    {
                        "name": "sleep_analysis",
                        "units": "hr",
                        "data": [
                            {
                                "source": "Apple Watch",
                                "totalSleep": 7.25,
                                "sleepEnd": "2026-08-29 07:15:00 +1000",
                                "date": "2026-08-29 00:00:00 +1000",
                            }
                        ],
                    },
                ]
            }
        }

        first = client.post("/ingest/apple-health", json=payload, headers={"Authorization": "Bearer test-secret"})
        second = client.post("/ingest/apple-health", json=payload, headers={"Authorization": "Bearer test-secret"})

        assert first.status_code == 200
        assert first.json()["imported"] == 3
        assert second.json()["duplicates"] == 3
        metrics = db_session.query(NormalizedMetric).all()
        by_name = {metric.metric_name: metric.value_numeric for metric in metrics}
        assert by_name == {
            "systolic_bp": 121,
            "diastolic_bp": 78,
            "heart_rate": 69.5,
            "min_heart_rate": 45,
            "max_heart_rate": 151,
            "sleep_duration": 7.25,
        }
    finally:
        app.dependency_overrides.clear()


def seed_api_strava_run(db_session) -> None:
    start = datetime.now(timezone.utc) - timedelta(days=1)
    start_local = start.astimezone(timezone(timedelta(hours=10)))
    activity = {
        "id": 321,
        "name": "400 m repeat session",
        "sport_type": "Run",
        "start_date": start.isoformat().replace("+00:00", "Z"),
        "start_date_local": start_local.isoformat(),
        "elapsed_time": 744,
        "distance": 1960,
    }
    store_raw_event(db_session, provider="strava", payload=activity, source_record_id=source_record_id_for_strava_activity(activity))
    store_raw_event(db_session, provider="strava", payload=activity, source_record_id=source_record_id_for_strava_activity_detail(321))
    laps = [
        {"lap_index": 1, "distance": 400, "elapsed_time": 96, "start_index": 0, "end_index": 95},
        {"lap_index": 2, "distance": 120, "elapsed_time": 120, "start_index": 96, "end_index": 215},
        {"lap_index": 3, "distance": 400, "elapsed_time": 96, "start_index": 216, "end_index": 311},
        {"lap_index": 4, "distance": 120, "elapsed_time": 120, "start_index": 312, "end_index": 431},
        {"lap_index": 5, "distance": 400, "elapsed_time": 96, "start_index": 432, "end_index": 527},
        {"lap_index": 6, "distance": 120, "elapsed_time": 120, "start_index": 528, "end_index": 647},
        {"lap_index": 7, "distance": 400, "elapsed_time": 96, "start_index": 648, "end_index": 743},
    ]
    time_values = list(range(744))
    distance_values = [float(index) for index in range(744)]
    heartrate_values = [150 + (index % 96) * 20 / 95 if index in range(0, 96) or index in range(216, 312) or index in range(432, 528) or index in range(648, 744) else 140 for index in range(744)]
    store_raw_event(
        db_session,
        provider="strava",
        payload={"activity_id": 321, "start_date": activity["start_date"], "laps": laps},
        source_record_id=source_record_id_for_strava_activity_laps(321),
    )
    store_raw_event(
        db_session,
        provider="strava",
        payload={"activity_id": 321, "start_date": activity["start_date"], "streams": {"time": {"data": time_values}, "distance": {"data": distance_values}, "heartrate": {"data": heartrate_values}}},
        source_record_id=source_record_id_for_strava_activity_streams(321),
    )
    db_session.commit()
