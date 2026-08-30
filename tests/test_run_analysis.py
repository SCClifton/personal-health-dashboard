from __future__ import annotations

from datetime import datetime, timezone

from health_dashboard.services.ingestion import store_raw_event
from health_dashboard.services.run_analysis import analyze_strava_run_recovery, recent_strava_runs
from health_dashboard.services.strava_sync import (
    source_record_id_for_strava_activity,
    source_record_id_for_strava_activity_detail,
    source_record_id_for_strava_activity_laps,
    source_record_id_for_strava_activity_streams,
)


def test_run_recovery_detects_four_400m_repeats(db_session) -> None:
    seed_strava_interval_run(db_session, repeat_count=4)

    analysis = analyze_strava_run_recovery(db_session, "999")

    assert analysis.confidence == "high"
    assert analysis.repeat_count == 4
    assert analysis.source_status == {"summary": True, "detail": True, "laps": True, "streams": True, "heartrate": True}
    assert analysis.repeats[0].distance_m == 400
    assert analysis.repeats[0].pace_sec_per_km is not None
    assert analysis.repeats[0].peak_hr_bpm is not None
    assert analysis.repeats[0].hr_drop_60s_bpm is not None
    assert analysis.repeats[0].hr_drop_60s_bpm > 0
    assert analysis.repeats[0].hr_at_next_rep_start_bpm is not None


def test_run_recovery_detects_five_400m_repeats(db_session) -> None:
    seed_strava_interval_run(db_session, repeat_count=5)

    analysis = analyze_strava_run_recovery(db_session, "999")

    assert analysis.confidence == "high"
    assert analysis.repeat_count == 5


def test_run_recovery_warns_when_heartrate_stream_is_missing(db_session) -> None:
    seed_strava_interval_run(db_session, include_heartrate=False)

    analysis = analyze_strava_run_recovery(db_session, "999")

    assert analysis.confidence == "insufficient"
    assert analysis.source_status["heartrate"] is False
    assert "Heart-rate stream is missing" in " ".join(analysis.warnings)
    assert analysis.repeats[0].hr_drop_60s_bpm is None


def test_run_recovery_warns_when_laps_are_missing(db_session) -> None:
    seed_strava_interval_run(db_session, include_laps=False)

    analysis = analyze_strava_run_recovery(db_session, "999")

    assert analysis.confidence == "insufficient"
    assert analysis.repeat_count == 0
    assert "Lap data is missing" in " ".join(analysis.warnings)


def test_recent_strava_runs_filters_by_timezone_aware_start(db_session) -> None:
    seed_strava_interval_run(db_session, start_date="2026-06-23T06:00:00Z")

    runs = recent_strava_runs(db_session, days=1, now=datetime(2026, 6, 23, 12, tzinfo=timezone.utc))

    assert [run.activity_id for run in runs] == ["999"]
    assert runs[0].has_laps is True
    assert runs[0].has_heartrate is True


def seed_strava_interval_run(
    db_session,
    *,
    activity_id: str = "999",
    repeat_count: int = 4,
    include_laps: bool = True,
    include_heartrate: bool = True,
    start_date: str = "2026-06-23T06:00:00Z",
) -> None:
    summary = {
        "id": int(activity_id),
        "name": "400 m repeat session",
        "sport_type": "Run",
        "start_date": start_date,
        "start_date_local": "2026-06-23T16:00:00+10:00",
        "elapsed_time": repeat_count * 96 + max(repeat_count - 1, 0) * 120,
        "distance": repeat_count * 400 + max(repeat_count - 1, 0) * 120,
    }
    store_raw_event(
        db_session,
        provider="strava",
        payload=summary,
        source_record_id=source_record_id_for_strava_activity(summary),
    )
    store_raw_event(
        db_session,
        provider="strava",
        payload=summary | {"description": "Detailed Strava activity payload"},
        source_record_id=source_record_id_for_strava_activity_detail(activity_id),
        permissions_scope="activity_detail",
    )
    streams, laps = interval_streams_and_laps(repeat_count=repeat_count, include_heartrate=include_heartrate)
    if include_laps:
        store_raw_event(
            db_session,
            provider="strava",
            payload={"activity_id": activity_id, "start_date": start_date, "laps": laps},
            source_record_id=source_record_id_for_strava_activity_laps(activity_id),
            permissions_scope="activity_laps",
        )
    store_raw_event(
        db_session,
        provider="strava",
        payload={"activity_id": activity_id, "start_date": start_date, "streams": streams},
        source_record_id=source_record_id_for_strava_activity_streams(activity_id),
        permissions_scope="activity_streams",
    )
    db_session.commit()


def interval_streams_and_laps(*, repeat_count: int, include_heartrate: bool) -> tuple[dict, list[dict]]:
    time_values: list[int] = []
    distance_values: list[float] = []
    heartrate_values: list[float] = []
    moving_values: list[bool] = []
    laps: list[dict] = []
    current_time = 0
    current_distance = 0.0
    lap_index = 1

    for rep in range(repeat_count):
        start_index = len(time_values)
        for second in range(96):
            time_values.append(current_time)
            current_distance += 400 / 96
            distance_values.append(current_distance)
            heartrate_values.append(150 + second * 20 / 95)
            moving_values.append(True)
            current_time += 1
        end_index = len(time_values) - 1
        laps.append({"lap_index": lap_index, "distance": 400, "elapsed_time": 96, "start_index": start_index, "end_index": end_index})
        lap_index += 1

        if rep < repeat_count - 1:
            start_index = len(time_values)
            for second in range(120):
                time_values.append(current_time)
                current_distance += 120 / 120
                distance_values.append(current_distance)
                heartrate_values.append(170 - second * 35 / 119)
                moving_values.append(True)
                current_time += 1
            end_index = len(time_values) - 1
            laps.append({"lap_index": lap_index, "distance": 120, "elapsed_time": 120, "start_index": start_index, "end_index": end_index})
            lap_index += 1

    streams = {
        "time": {"data": time_values},
        "distance": {"data": distance_values},
        "moving": {"data": moving_values},
    }
    if include_heartrate:
        streams["heartrate"] = {"data": heartrate_values}
    return streams, laps
