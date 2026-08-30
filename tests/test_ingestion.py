from datetime import date, datetime
from zoneinfo import ZoneInfo

from health_dashboard.models import DailyFeature, RawEvent
from health_dashboard.connectors.csv_imports import parse_csv_metrics, parse_zip_metrics
from health_dashboard.services.ingestion import rebuild_daily_features, store_raw_event
from health_dashboard.services.medication import log_tirzepatide_dose
from health_dashboard.services.normalization import metric_from_payload
from health_dashboard.services.time import local_date, parse_datetime


def test_idempotent_import_by_source_id(db_session) -> None:
    payload = {"id": "bp-1", "metric_name": "systolic_bp", "value": 122, "unit": "mmHg", "date": "2026-05-03T08:00:00+10:00", "source": "manual_cuff"}
    first, created_first = store_raw_event(db_session, provider="bp", payload=payload)
    second, created_second = store_raw_event(db_session, provider="bp", payload=payload)
    db_session.commit()

    assert first.id == second.id
    assert created_first is True
    assert created_second is False
    assert db_session.query(RawEvent).count() == 1


def test_idempotent_import_by_payload_hash_without_source_id(db_session) -> None:
    payload = {"metric_name": "weight", "value": 180, "unit": "lb", "date": "2026-05-03T08:00:00+10:00", "source": "manual"}
    _, created_first = store_raw_event(db_session, provider="weight", payload=payload)
    _, created_second = store_raw_event(db_session, provider="weight", payload=payload)
    db_session.commit()

    assert created_first is True
    assert created_second is False
    assert db_session.query(RawEvent).count() == 1


def test_timezone_local_date() -> None:
    observed = parse_datetime("2026-05-02T15:30:00Z")
    assert observed is not None
    assert local_date(observed, "Australia/Sydney") == date(2026, 5, 3)


def test_local_evening_medication_dose_stays_on_local_day(db_session) -> None:
    log_tirzepatide_dose(
        db_session,
        dose_mg=2.5,
        taken_at=datetime(2026, 4, 24, 20, 0, tzinfo=ZoneInfo("Australia/Sydney")),
    )
    db_session.commit()

    feature = db_session.get(DailyFeature, {"date": date(2026, 4, 24), "timezone": "Australia/Sydney"})

    assert feature is not None
    assert feature.tirzepatide_dose_mg == 2.5
    assert feature.tirzepatide_days_since_dose == 0


def test_direct_bp_beats_apple_health_summary(db_session) -> None:
    apple_payload = {"id": "apple-bp", "metric_name": "systolic_bp", "value": 135, "unit": "mmHg", "date": "2026-05-03T08:00:00+10:00", "source": "apple_health"}
    cuff_payload = {"id": "cuff-bp", "metric_name": "systolic_bp", "value": 121, "unit": "mmHg", "date": "2026-05-03T08:30:00+10:00", "source": "manual_cuff"}
    store_raw_event(db_session, provider="apple_health", payload=apple_payload, metrics=[metric_from_payload("apple_health", apple_payload)])
    store_raw_event(db_session, provider="bp", payload=cuff_payload, metrics=[metric_from_payload("bp", cuff_payload)])
    rebuild_daily_features(db_session, tz_name="Australia/Sydney")
    db_session.commit()

    feature = db_session.get(DailyFeature, {"date": date(2026, 5, 3), "timezone": "Australia/Sydney"})
    assert feature is not None
    assert feature.systolic_bp == 121
    assert feature.source_flags["systolic_bp"] == ["manual_cuff"]


def test_hilo_bp_source_beats_generic_apple_health_summary(db_session) -> None:
    apple_payload = {"id": "apple-bp", "metric_name": "systolic_bp", "value": 135, "unit": "mmHg", "date": "2026-05-03T08:00:00+10:00", "source": "apple_health"}
    hilo_payload = {"id": "hilo-bp", "metric_name": "systolic_bp", "value": 126, "unit": "mmHg", "date": "2026-05-03T08:30:00+10:00", "source": "Hilo"}
    store_raw_event(db_session, provider="apple_health", payload=apple_payload, metrics=[metric_from_payload("apple_health", apple_payload)])
    store_raw_event(db_session, provider="apple_health", payload=hilo_payload, metrics=[metric_from_payload("apple_health", hilo_payload)])
    rebuild_daily_features(db_session, tz_name="Australia/Sydney")
    db_session.commit()

    feature = db_session.get(DailyFeature, {"date": date(2026, 5, 3), "timezone": "Australia/Sydney"})
    assert feature is not None
    assert feature.systolic_bp == 126
    assert feature.source_flags["systolic_bp"] == ["Hilo"]


def test_apple_health_aliases_current_export_names() -> None:
    hrv_payload = {"metric_name": "heart_rate_variability", "value": 42, "unit": "ms", "date": "2026-05-03T08:00:00+10:00"}
    weight_payload = {"metric_name": "weight_body_mass", "value": 82, "unit": "kg", "date": "2026-05-03T08:00:00+10:00"}

    hrv = metric_from_payload("apple_health", hrv_payload)
    weight = metric_from_payload("apple_health", weight_payload)

    assert hrv is not None
    assert hrv.metric_name == "hrv"
    assert weight is not None
    assert weight.metric_name == "weight"


def test_sleep_duration_rollup_merges_overlapping_intervals_by_source(db_session) -> None:
    first = {
        "id": "sleep-1",
        "metric_name": "sleep_duration",
        "value": 8,
        "unit": "h",
        "observed_start": "2026-05-02T22:00:00+10:00",
        "observed_end": "2026-05-03T06:00:00+10:00",
        "source": "WHOOP",
    }
    overlapping = {
        "id": "sleep-2",
        "metric_name": "sleep_duration",
        "value": 2,
        "unit": "h",
        "observed_start": "2026-05-03T01:00:00+10:00",
        "observed_end": "2026-05-03T03:00:00+10:00",
        "source": "WHOOP",
    }
    lower_priority = {
        "id": "sleep-3",
        "metric_name": "sleep_duration",
        "value": 9,
        "unit": "h",
        "observed_start": "2026-05-02T21:00:00+10:00",
        "observed_end": "2026-05-03T06:00:00+10:00",
        "source": "Eight Sleep",
    }

    for payload in (first, overlapping, lower_priority):
        store_raw_event(db_session, provider="apple_health", payload=payload, metrics=[metric_from_payload("apple_health", payload)])
    rebuild_daily_features(db_session, tz_name="Australia/Sydney")
    db_session.commit()

    feature = db_session.get(DailyFeature, {"date": date(2026, 5, 3), "timezone": "Australia/Sydney"})
    assert feature is not None
    assert feature.sleep_duration == 8
    assert feature.source_flags["sleep_duration"] == ["WHOOP"]


def test_myfitnesspal_export_columns_parse_nutrition_weight_and_exercise() -> None:
    content = (
        "Date,Calories,Protein (g),Carbohydrates (g),Fat (g),Weight (lbs),Exercise,Exercise Calories,Steps\n"
        "2026-05-03,1800,160,180,60,250,Run,400,8379\n"
    ).encode()

    rows = parse_csv_metrics(content, provider="nutrition", source="myfitnesspal")

    metrics = rows[0][1]
    by_name = {metric.metric_name: metric for metric in metrics}
    assert by_name["calories"].value_numeric == 1800
    assert by_name["protein"].value_numeric == 160
    assert by_name["carbs"].value_numeric == 180
    assert by_name["fat"].value_numeric == 60
    assert round(by_name["weight"].value_numeric or 0, 2) == 113.4
    assert by_name["active_energy"].value_numeric == 400
    assert by_name["steps"].value_numeric == 8379
    assert by_name["workout_count"].value_numeric == 1


def test_hilo_csv_uses_observed_at_local_and_stable_bp_id() -> None:
    content = (
        "observed_at_local,date,time,systolic_bp,diastolic_bp,heart_rate,period\n"
        "2026-05-30T21:22,2026-05-30,21:22,145,80,51,day\n"
    ).encode()

    rows = parse_csv_metrics(content, provider="bp", source="hilo_pdf_report")

    payload, metrics = rows[0]
    by_name = {metric.metric_name: metric for metric in metrics}
    assert payload["id"] == "hilo_pdf_report:bp:2026-05-30T21:22:145:80:51"
    assert by_name["systolic_bp"].observed_start.isoformat() == "2026-05-30T11:22:00+00:00"
    assert by_name["diastolic_bp"].observed_start.isoformat() == "2026-05-30T11:22:00+00:00"
    assert by_name["systolic_bp"].source == "hilo_pdf_report"


def test_myfitnesspal_zip_preserves_filename_in_source() -> None:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Nutrition-Summary.csv", "Date,Calories,Protein (g)\n2026-05-03,1800,160\n")

    rows = parse_zip_metrics(buffer.getvalue(), provider="nutrition", source="myfitnesspal")

    assert rows[0][1][0].source == "myfitnesspal:Nutrition-Summary.csv"


def test_myfitnesspal_same_day_rows_sum_as_events(db_session) -> None:
    content = (
        "Date,Meal,Calories,Protein (g),Exercise,Exercise Calories,Steps\n"
        "2026-06-01,Breakfast,600,50,,,\n"
        "2026-06-01,Dinner,1000,110,,,\n"
        "2026-06-01,, , ,Run,300,7000\n"
        "2026-06-01,, , ,Walk,150,\n"
    ).encode()

    for payload, metrics in parse_csv_metrics(content, provider="nutrition", source="myfitnesspal:Summary.csv"):
        store_raw_event(db_session, provider="nutrition", payload=payload, metrics=metrics)
    rebuild_daily_features(db_session, tz_name="Australia/Sydney")
    db_session.commit()

    feature = db_session.get(DailyFeature, {"date": date(2026, 6, 1), "timezone": "Australia/Sydney"})
    assert feature is not None
    assert feature.calories == 1600
    assert feature.protein == 160
    assert feature.active_energy == 450
    assert feature.steps == 7000
    assert feature.workout_count == 2


def test_activity_rollup_uses_best_source_without_double_counting(db_session) -> None:
    mfp_payload = {
        "id": "mfp-exercise-1",
        "metric_name": "active_energy",
        "value": 300,
        "unit": "kcal",
        "date": "2026-06-01T09:00:00+10:00",
        "source": "myfitnesspal:Exercise-Summary.csv",
        "aggregation_window": "event",
    }
    whoop_payload = {
        "id": "whoop-cycle-1",
        "metric_name": "active_energy",
        "value": 1200,
        "unit": "kilojoule",
        "date": "2026-06-01T09:00:00+10:00",
        "source": "whoop",
        "aggregation_window": "event",
    }

    store_raw_event(db_session, provider="nutrition", payload=mfp_payload)
    store_raw_event(db_session, provider="whoop", payload=whoop_payload)
    rebuild_daily_features(db_session, tz_name="Australia/Sydney")
    db_session.commit()

    feature = db_session.get(DailyFeature, {"date": date(2026, 6, 1), "timezone": "Australia/Sydney"})
    assert feature is not None
    assert round(feature.active_energy or 0, 2) == 286.81
    assert feature.source_flags["active_energy"] == ["whoop"]


def test_activity_rollup_collapses_repeated_apple_health_snapshots(db_session) -> None:
    older = {
        "id": "apple-steps-old",
        "metric_name": "steps",
        "value": 1000,
        "unit": "count",
        "date": "2026-06-01T00:00:00+10:00",
        "source": "S Clifton",
        "aggregation_window": "health_auto_export_v2",
    }
    newer = {
        "id": "apple-steps-new",
        "metric_name": "steps",
        "value": 1200,
        "unit": "count",
        "date": "2026-06-01T00:00:00+10:00",
        "source": "WHOOP|S Clifton",
        "aggregation_window": "health_auto_export_v2",
    }

    store_raw_event(db_session, provider="apple_health", payload=older)
    store_raw_event(db_session, provider="apple_health", payload=newer)
    rebuild_daily_features(db_session, tz_name="Australia/Sydney")
    db_session.commit()

    feature = db_session.get(DailyFeature, {"date": date(2026, 6, 1), "timezone": "Australia/Sydney"})
    assert feature is not None
    assert feature.steps == 1200
    assert feature.source_flags["steps"] == ["WHOOP|S Clifton"]
