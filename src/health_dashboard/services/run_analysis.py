from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from health_dashboard.models import RawEvent
from health_dashboard.services.strava_sync import is_strava_run
from health_dashboard.services.time import parse_datetime


@dataclass(frozen=True)
class RunListItem:
    activity_id: str
    provider: str
    name: str
    start_date: datetime | None
    start_date_local: str | None
    distance_m: float | None
    elapsed_time_s: float | None
    has_summary: bool
    has_detail: bool
    has_laps: bool
    has_streams: bool
    has_heartrate: bool


@dataclass(frozen=True)
class TimelinePoint:
    time_s: float
    distance_m: float | None
    heartrate_bpm: float | None
    cadence: float | None
    moving: bool | None


@dataclass(frozen=True)
class RunRepeatRecovery:
    rep_number: int
    lap_index: int | None
    distance_m: float | None
    duration_s: float | None
    pace_sec_per_km: float | None
    rest_duration_s: float | None
    peak_hr_bpm: float | None
    hr_at_rest_start_bpm: float | None
    hr_60s_bpm: float | None
    hr_drop_60s_bpm: float | None
    hr_120s_bpm: float | None
    hr_drop_120s_bpm: float | None
    min_rest_hr_bpm: float | None
    hr_at_next_rep_start_bpm: float | None


@dataclass(frozen=True)
class RunRecoveryAnalysis:
    activity_id: str
    provider: str
    name: str
    start_date: datetime | None
    distance_m: float | None
    elapsed_time_s: float | None
    repeat_count: int
    confidence: str
    warnings: list[str]
    source_status: dict[str, bool]
    repeats: list[RunRepeatRecovery]


@dataclass(frozen=True)
class LapWindow:
    lap_index: int | None
    start_s: float
    end_s: float
    distance_m: float | None
    duration_s: float | None


def recent_strava_runs(db: Session, *, days: int = 14, now: datetime | None = None) -> list[RunListItem]:
    now_utc = _aware_utc(now or datetime.now(timezone.utc))
    cutoff = now_utc - timedelta(days=days)
    parts = _strava_activity_parts(db)
    items: list[RunListItem] = []
    for activity_id, payloads in parts.items():
        summary = payloads.get("summary")
        detail = payloads.get("detail")
        activity = detail or summary
        if not activity or not is_strava_run(activity):
            continue
        start = _activity_start(activity)
        if start and _aware_utc(start) < cutoff:
            continue
        streams = _streams_payload(payloads.get("streams"))
        items.append(
            RunListItem(
                activity_id=activity_id,
                provider="strava",
                name=str(activity.get("name") or "Strava run"),
                start_date=start,
                start_date_local=activity.get("start_date_local"),
                distance_m=_float_or_none(activity.get("distance")),
                elapsed_time_s=_float_or_none(activity.get("elapsed_time")),
                has_summary=summary is not None,
                has_detail=detail is not None,
                has_laps=payloads.get("laps") is not None,
                has_streams=streams is not None,
                has_heartrate=_has_stream(streams, "heartrate"),
            )
        )
    return sorted(items, key=lambda item: item.start_date or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


def analyze_strava_run_recovery(db: Session, activity_id: int | str) -> RunRecoveryAnalysis:
    activity_key = str(activity_id)
    parts = _strava_activity_parts(db).get(activity_key, {})
    summary = parts.get("summary")
    detail = parts.get("detail")
    activity = detail or summary or {}
    laps = _laps_payload(parts.get("laps"))
    streams = _streams_payload(parts.get("streams"))
    timeline = timeline_from_streams(streams)
    warnings: list[str] = []

    if not activity:
        warnings.append("No Strava activity summary or detail is stored locally for this run.")
    if detail is None:
        warnings.append("Activity detail is missing; run the rich Strava run sync before relying on this analysis.")
    if not laps:
        warnings.append("Lap data is missing; 400 m repeat detection needs Strava/Garmin lap boundaries.")
    if not streams:
        warnings.append("Stream data is missing; heart-rate recovery cannot be computed from summary data alone.")
    elif not _has_stream(streams, "heartrate"):
        warnings.append("Heart-rate stream is missing; recovery drops cannot be computed.")

    work_laps = detect_400m_work_laps(laps, timeline)
    if work_laps and len(work_laps) not in {4, 5}:
        warnings.append(f"Detected {len(work_laps)} 350-450 m laps, not the expected 4-5 repeats.")
    elif not work_laps and laps:
        warnings.append("No 350-450 m work laps were detected.")

    repeats = repeat_recovery_from_laps(work_laps, timeline)
    confidence = _confidence(parts=parts, streams=streams, work_laps=work_laps)
    return RunRecoveryAnalysis(
        activity_id=activity_key,
        provider="strava",
        name=str(activity.get("name") or "Strava run"),
        start_date=_activity_start(activity),
        distance_m=_float_or_none(activity.get("distance")),
        elapsed_time_s=_float_or_none(activity.get("elapsed_time")),
        repeat_count=len(repeats),
        confidence=confidence,
        warnings=warnings,
        source_status={
            "summary": summary is not None,
            "detail": detail is not None,
            "laps": bool(laps),
            "streams": bool(streams),
            "heartrate": _has_stream(streams, "heartrate"),
        },
        repeats=repeats,
    )


def timeline_from_streams(streams: dict[str, Any] | None) -> list[TimelinePoint]:
    if not streams:
        return []
    time_values = _stream_values(streams, "time")
    distance_values = _stream_values(streams, "distance")
    hr_values = _stream_values(streams, "heartrate")
    cadence_values = _stream_values(streams, "cadence")
    moving_values = _stream_values(streams, "moving")
    max_len = max((len(values) for values in (time_values, distance_values, hr_values, cadence_values, moving_values)), default=0)
    points: list[TimelinePoint] = []
    for index in range(max_len):
        time_value = _value_at(time_values, index)
        if time_value is None:
            continue
        points.append(
            TimelinePoint(
                time_s=float(time_value),
                distance_m=_float_or_none(_value_at(distance_values, index)),
                heartrate_bpm=_float_or_none(_value_at(hr_values, index)),
                cadence=_float_or_none(_value_at(cadence_values, index)),
                moving=_bool_or_none(_value_at(moving_values, index)),
            )
        )
    return points


def detect_400m_work_laps(laps: list[dict[str, Any]], timeline: list[TimelinePoint]) -> list[LapWindow]:
    windows: list[LapWindow] = []
    cursor_s = 0.0
    for fallback_index, lap in enumerate(laps, start=1):
        window = lap_window(lap, timeline, cursor_s, fallback_index=fallback_index)
        cursor_s = window.end_s
        if window.distance_m is not None and 350 <= window.distance_m <= 450:
            windows.append(window)
    return windows


def repeat_recovery_from_laps(work_laps: list[LapWindow], timeline: list[TimelinePoint]) -> list[RunRepeatRecovery]:
    repeats: list[RunRepeatRecovery] = []
    latest_time = timeline[-1].time_s if timeline else None
    for index, lap in enumerate(work_laps):
        next_lap = work_laps[index + 1] if index + 1 < len(work_laps) else None
        rest_start = lap.end_s
        rest_end = next_lap.start_s if next_lap else min(rest_start + 120, latest_time) if latest_time is not None else rest_start
        work_points = points_in_window(timeline, lap.start_s, lap.end_s)
        rest_points = points_in_window(timeline, rest_start, rest_end)
        rest_start_hr = hr_near(timeline, rest_start)
        hr_60 = hr_near(timeline, rest_start + 60) if rest_end >= rest_start + 60 else None
        hr_120 = hr_near(timeline, rest_start + 120) if rest_end >= rest_start + 120 else None
        repeats.append(
            RunRepeatRecovery(
                rep_number=index + 1,
                lap_index=lap.lap_index,
                distance_m=lap.distance_m,
                duration_s=lap.duration_s,
                pace_sec_per_km=pace_sec_per_km(lap.distance_m, lap.duration_s),
                rest_duration_s=max(rest_end - rest_start, 0),
                peak_hr_bpm=max((point.heartrate_bpm for point in work_points if point.heartrate_bpm is not None), default=None),
                hr_at_rest_start_bpm=rest_start_hr,
                hr_60s_bpm=hr_60,
                hr_drop_60s_bpm=_drop(rest_start_hr, hr_60),
                hr_120s_bpm=hr_120,
                hr_drop_120s_bpm=_drop(rest_start_hr, hr_120),
                min_rest_hr_bpm=min((point.heartrate_bpm for point in rest_points if point.heartrate_bpm is not None), default=None),
                hr_at_next_rep_start_bpm=hr_near(timeline, next_lap.start_s) if next_lap else None,
            )
        )
    return repeats


def lap_window(lap: dict[str, Any], timeline: list[TimelinePoint], cursor_s: float, *, fallback_index: int) -> LapWindow:
    start_s = _time_at_index(timeline, lap.get("start_index"))
    end_s = _time_at_index(timeline, lap.get("end_index"))
    duration = _float_or_none(lap.get("elapsed_time") or lap.get("moving_time"))
    if start_s is None:
        start_s = cursor_s
    if end_s is None:
        end_s = start_s + (duration or 0)
    if duration is None and end_s >= start_s:
        duration = end_s - start_s
    return LapWindow(
        lap_index=_int_or_none(lap.get("lap_index") or lap.get("split") or fallback_index),
        start_s=start_s,
        end_s=end_s,
        distance_m=_float_or_none(lap.get("distance")),
        duration_s=duration,
    )


def points_in_window(timeline: list[TimelinePoint], start_s: float, end_s: float) -> list[TimelinePoint]:
    return [point for point in timeline if start_s <= point.time_s <= end_s]


def hr_near(timeline: list[TimelinePoint], target_s: float, *, tolerance_s: float = 10) -> float | None:
    candidates = [point for point in timeline if point.heartrate_bpm is not None]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda point: abs(point.time_s - target_s))
    if abs(nearest.time_s - target_s) > tolerance_s:
        return None
    return nearest.heartrate_bpm


def pace_sec_per_km(distance_m: float | None, duration_s: float | None) -> float | None:
    if distance_m is None or duration_s is None or distance_m <= 0:
        return None
    return duration_s / (distance_m / 1000)


def _strava_activity_parts(db: Session) -> dict[str, dict[str, dict[str, Any]]]:
    rows = db.query(RawEvent).filter(RawEvent.provider == "strava").all()
    parts: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        source_id = row.source_record_id or ""
        parsed = _parse_strava_source_id(source_id)
        if parsed is None:
            continue
        activity_id, part = parsed
        payload = row.payload_json or {}
        parts.setdefault(activity_id, {})[part] = payload
    return parts


def _parse_strava_source_id(source_id: str) -> tuple[str, str] | None:
    chunks = source_id.split(":")
    if len(chunks) == 2 and chunks[0] == "activity":
        return chunks[1], "summary"
    if len(chunks) == 3 and chunks[0] == "activity":
        part = chunks[2]
        if part in {"detail", "laps", "streams"}:
            return chunks[1], part
    return None


def _activity_start(activity: dict[str, Any]) -> datetime | None:
    return parse_datetime(activity.get("start_date") or activity.get("start_date_local") or activity.get("observed_start"))


def _laps_payload(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    laps = payload.get("laps", payload)
    return laps if isinstance(laps, list) else []


def _streams_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    streams = payload.get("streams", payload)
    return streams if isinstance(streams, dict) else {}


def _stream_values(streams: dict[str, Any], key: str) -> list[Any]:
    stream = streams.get(key)
    if isinstance(stream, dict):
        data = stream.get("data")
        return data if isinstance(data, list) else []
    return stream if isinstance(stream, list) else []


def _has_stream(streams: dict[str, Any] | None, key: str) -> bool:
    return bool(_stream_values(streams or {}, key))


def _value_at(values: list[Any], index: int) -> Any:
    return values[index] if index < len(values) else None


def _time_at_index(timeline: list[TimelinePoint], raw_index: Any) -> float | None:
    index = _int_or_none(raw_index)
    if index is None or index < 0 or index >= len(timeline):
        return None
    return timeline[index].time_s


def _confidence(*, parts: dict[str, dict[str, Any]], streams: dict[str, Any], work_laps: list[LapWindow]) -> str:
    if not parts.get("summary") and not parts.get("detail"):
        return "insufficient"
    if not parts.get("laps") or not streams or not _has_stream(streams, "heartrate") or not work_laps:
        return "insufficient"
    if len(work_laps) in {4, 5}:
        return "high"
    return "medium"


def _drop(start: float | None, later: float | None) -> float | None:
    if start is None or later is None:
        return None
    return start - later


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)
