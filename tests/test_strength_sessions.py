from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from health_dashboard.api.schemas import StrengthSessionIn
from health_dashboard.db import get_db
from health_dashboard.main import app
from health_dashboard.models import NormalizedMetric, RawEvent, StrengthExercise, StrengthSession, StrengthSet
from health_dashboard.services.strength import import_strength_session, payload_totals, serialize_strength_session


def session_payload(**overrides) -> dict:
    payload = {
        "source_record_id": "voice:2026-09-07:98-performance:w10b3:sts",
        "source_kind": "voice",
        "source_text": "Strict press: 3 at 64 kg, then six rows each side at 30 kg.",
        "capture_status": "complete",
        "started_at": "2026-09-07T06:30:00+10:00",
        "duration_seconds": 3600,
        "timezone": "Australia/Sydney",
        "timing_confidence": "estimated",
        "program_name": "98 Performance",
        "program_session_name": "Strength + Sprint",
        "program_week": 10,
        "program_block": 3,
        "program_notes": "Planned sprint work follows the strength series.",
        "session_rpe": 8,
        "exercises": [
            {
                "position": 1,
                "series_name": "Series 1",
                "name": "Barbell Strict Press",
                "planned_reps": "3-2-1-1+",
                "planned_tempo": "10X1",
                "planned_rest_seconds": 30,
                "target_intensity": "80/85/90/90%",
                "planned_notes": "App coach note.",
                "sets": [{"position": 1, "reps": 3, "load_value": 64, "load_unit": "kg", "rpe": 8}],
            },
            {
                "position": 2,
                "series_name": "Series 2",
                "name": "Supported Single Arm Dumbbell Row",
                "planned_reps": "4 x 6.6",
                "target_intensity": "RPE 8",
                "sets": [
                    {
                        "position": 1,
                        "reps": 6,
                        "rep_multiplier": 2,
                        "load_value": 30,
                        "load_unit": "kg",
                        "notes": "Six reps each side.",
                    }
                ],
            },
        ],
    }
    payload.update(overrides)
    return payload


def test_strength_session_preserves_voice_input_and_computes_load(db_session) -> None:
    payload = StrengthSessionIn.model_validate(session_payload())

    session, created = import_strength_session(db_session, payload)
    db_session.commit()

    assert created is True
    assert db_session.query(StrengthSession).count() == 1
    assert db_session.query(StrengthExercise).count() == 2
    assert db_session.query(StrengthSet).count() == 2
    raw = db_session.query(RawEvent).filter(RawEvent.provider == "manual_strength").one()
    assert raw.source_record_id == payload.source_record_id
    assert raw.payload_json["source_text"] == payload.source_text
    assert raw.schema_version == "strength_session.v1"
    assert raw.observed_start.replace(tzinfo=timezone.utc).isoformat() == "2026-09-06T20:30:00+00:00"
    assert session.started_at.replace(tzinfo=timezone.utc).isoformat() == "2026-09-06T20:30:00+00:00"
    assert session.program_notes == "Planned sprint work follows the strength series."
    assert session.exercises[0].planned_notes == "App coach note."

    totals = payload_totals(payload)
    assert totals["set_count"] == 2
    assert totals["rep_count"] == 15
    assert totals["volume_load_kg"] == 552
    metrics = {item.metric_name: item for item in db_session.query(NormalizedMetric).all()}
    assert metrics["strength_session_count"].value_numeric == 1
    assert metrics["strength_set_count"].value_numeric == 2
    assert metrics["strength_rep_count"].value_numeric == 15
    assert metrics["strength_volume_load"].value_numeric == 552
    assert metrics["strength_duration"].value_numeric == 1
    assert metrics["strength_session_rpe"].value_numeric == 8
    assert metrics["strength_volume_load"].unit == "kg-reps"
    assert "workout_count" not in metrics


def test_strength_session_duplicate_source_id_is_idempotent(db_session) -> None:
    payload = StrengthSessionIn.model_validate(session_payload())

    first, first_created = import_strength_session(db_session, payload)
    second, second_created = import_strength_session(db_session, payload)
    db_session.commit()

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert db_session.query(RawEvent).filter(RawEvent.provider == "manual_strength").count() == 1
    assert db_session.query(StrengthSession).count() == 1


def test_strength_loads_normalize_pounds_without_losing_reported_unit(db_session) -> None:
    data = session_payload()
    data["exercises"] = [
        {
            "position": 1,
            "name": "Bench Press",
            "sets": [{"position": 1, "reps": 5, "load_value": 100, "load_unit": "lb"}],
        }
    ]
    payload = StrengthSessionIn.model_validate(data)

    session, _ = import_strength_session(db_session, payload)
    db_session.commit()

    stored_set = session.exercises[0].sets[0]
    assert stored_set.load_value == 100
    assert stored_set.load_unit == "lb"
    assert stored_set.load_kg == pytest.approx(45.359237)
    assert serialize_strength_session(session)["totals"]["volume_load_kg"] == pytest.approx(226.796185)


def test_partial_strength_session_allows_missing_set_detail(db_session) -> None:
    data = session_payload(capture_status="partial")
    data["exercises"] = [
        {
            "position": 1,
            "name": "Sandbag Carry",
            "status": "unknown",
            "planned_sets": "3 x 60m",
            "target_intensity": "RPE 8",
            "sets": [],
        }
    ]
    payload = StrengthSessionIn.model_validate(data)

    session, created = import_strength_session(db_session, payload)
    db_session.commit()

    assert created is True
    assert session.capture_status == "partial"
    assert session.exercises[0].sets == []
    assert serialize_strength_session(session)["totals"] == {
        "set_count": 0,
        "rep_count": 0,
        "volume_load_kg": 0,
        "distance_meters": 0,
        "duration_seconds": 3600,
        "average_set_rpe": 0,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"started_at": "2026-09-07T06:30:00"},
        {"timezone": "Sydney/Invalid"},
        {"source_text": ""},
        {"ended_at": "2026-09-07T06:00:00+10:00"},
        {"exercises": [{"position": 1, "name": "A"}, {"position": 1, "name": "B"}]},
        {"exercises": [{"position": 1, "name": "A", "sets": [{"position": 1}, {"position": 1}]}]},
        {"exercises": [], "capture_status": "complete"},
        {
            "exercises": [
                {"position": 1, "name": "A", "sets": [{"position": 1, "status": "skipped"}]}
            ],
            "capture_status": "complete",
        },
    ],
)
def test_strength_session_validation_rejects_invalid_or_ambiguous_data(changes) -> None:
    with pytest.raises(ValidationError):
        StrengthSessionIn.model_validate(session_payload(**changes))


def test_strength_session_api_stores_and_lists_session(db_session) -> None:
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        first = client.post("/strength-sessions", json=session_payload())
        duplicate = client.post("/strength-sessions", json=session_payload())
        recent = client.get("/api/strength-sessions?days=3650")

        assert first.status_code == 200
        assert first.json()["imported"] == 1
        assert duplicate.status_code == 200
        assert duplicate.json()["duplicates"] == 1
        assert recent.status_code == 200
        assert recent.json()[0]["program_session_name"] == "Strength + Sprint"
        assert recent.json()[0]["totals"]["volume_load_kg"] == 552
    finally:
        app.dependency_overrides.clear()
