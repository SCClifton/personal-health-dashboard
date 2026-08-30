#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any
from urllib.parse import quote
from zipfile import ZipFile
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZIP = Path("/Users/samuelclifton/Downloads/eight_sleep_data.zip")
DEFAULT_WHOOP_DB = Path("/Users/samuelclifton/Developer/personal-health-dashboard/data/health_dashboard.db")
DEFAULT_OUT = ROOT / "local_exports" / "eight_sleep_whoop_concordance"
DEFAULT_TZ = "Australia/Sydney"
SLEEP_STAGES = {"light", "deep", "rem"}
FAMILY_WINDOW_START = time(18, 30)
FAMILY_WINDOW_END = time(20, 0)


MEASUREMENT_MODEL = [
    {
        "source": "Eight Sleep",
        "model": "Bed/side-level passive sensing from the Pod cover.",
        "evidence": [
            "Eight Sleep describes Pod 5 as a cover that tracks sleep and says each side controls independently.",
            "Eight Sleep states Autopilot monitors heart rate, HRV, respiratory rate, and sleep stages.",
            "Eight Sleep describes two separate users per Pod, but this export does not expose side/user/occupancy fields for each session.",
        ],
        "analysis_rule": "Use Eight Sleep as bed/side context unless the export identifies the sleeper. Early starts and longer intervals are evidence of occupancy or signal mixing, not definitive evidence that Sam was asleep.",
        "urls": [
            "https://www.eightsleep.com/au/product/pod-cover/",
            "https://www.eightsleep.com/blog/how-the-pod-detects-your-breathing-and-heartbeats-without-a-wearable/",
        ],
    },
    {
        "source": "WHOOP",
        "model": "Person-worn wrist/body sensor using optical PPG plus movement inputs.",
        "evidence": [
            "WHOOP says it measures heart rate using PPG, filters movement artifacts, and collects heart-rate data every second.",
            "WHOOP developer docs expose sleep start/end, nap flag, score state, and duration per sleep stage through read:sleep.",
            "WHOOP Recovery includes resting HR, HRV, respiratory rate, sleep duration/quality, skin temperature, and blood oxygen.",
        ],
        "analysis_rule": "Use direct WHOOP sleep as the primary person-level anchor for Sam in this first pass; exclude WHOOP naps from the main nightly comparison.",
        "urls": [
            "https://www.whoop.com/au/en/thelocker/a-look-behind-the-data-how-whoop-measures-heart-rate/",
            "https://developer.whoop.com/docs/developing/user-data/sleep/",
            "https://developer.whoop.com/api/",
            "https://developer.whoop.com/docs/whoop-101/",
        ],
    },
    {
        "source": "Oura",
        "model": "Person-worn finger ring using PPG, temperature, and accelerometer signals.",
        "evidence": [
            "Oura Ring 4 uses red/infrared LEDs for SpO2, green/infrared PPG for heart rate and HRV, a temperature sensor, and an accelerometer.",
            "Oura says sleep staging uses movement, skin temperature, resting HR, HRV, and respiratory rate, with 79% agreement against PSG in its cited algorithm validation.",
            "Oura estimates respiratory rate from minute-by-minute nighttime heart-rate/IBI changes.",
        ],
        "analysis_rule": "Use Oura as a second person-worn comparator once local Oura sleep data is available; until then, keep it out of the numeric concordance.",
        "urls": [
            "https://support.ouraring.com/hc/en-us/articles/33045011508115-Oura-Ring-4",
            "https://support.ouraring.com/hc/en-us/articles/11752397946003-Sleep-Stages",
            "https://support.ouraring.com/hc/en-us/articles/360025443174-Respiratory-Rate",
            "https://cloud.ouraring.com/docs/authentication",
        ],
    },
]


@dataclass(frozen=True)
class ArtifactPaths:
    report: Path
    overlap_csv: Path
    audit_csv: Path
    summary_json: Path


def parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def local_date(dt: datetime, tz: ZoneInfo) -> date:
    return dt.astimezone(tz).date()


def local_stamp(dt: datetime | None, tz: ZoneInfo) -> str:
    if dt is None:
        return ""
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def fmt_delta_minutes(value: float | None) -> str:
    if value is None:
        return ""
    rounded = int(round(value))
    sign = "+" if rounded >= 0 else "-"
    rounded = abs(rounded)
    return f"{sign}{rounded // 60:02d}:{rounded % 60:02d}"


def round_or_none(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def hours(seconds: float | int | None) -> float | None:
    if seconds is None:
        return None
    return float(seconds) / 3600


def millis_to_hours(value: float | int | None) -> float | None:
    if value is None:
        return None
    return float(value) / 1000 / 60 / 60


def series_stats(values: list[Any]) -> dict[str, Any]:
    samples: list[float] = []
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    for item in values:
        if not isinstance(item, list) or len(item) < 2 or item[1] is None:
            continue
        try:
            numeric = float(item[1])
        except (TypeError, ValueError):
            continue
        samples.append(numeric)
        ts = parse_dt(item[0])
        if ts and first_ts is None:
            first_ts = ts
        if ts:
            last_ts = ts
    if not samples:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None, "first": first_ts, "last": last_ts}
    return {
        "count": len(samples),
        "mean": mean(samples),
        "median": median(samples),
        "min": min(samples),
        "max": max(samples),
        "first": first_ts,
        "last": last_ts,
    }


def first_stage_time(start: datetime, stages: list[dict[str, Any]], wanted: set[str] | None = None, *, exclude_out: bool = False) -> datetime | None:
    elapsed = 0.0
    for stage in stages:
        name = str(stage.get("stage") or "").lower()
        duration = float(stage.get("duration") or 0)
        if wanted is not None and name in wanted:
            return start + timedelta(seconds=elapsed)
        if exclude_out and name != "out":
            return start + timedelta(seconds=elapsed)
        elapsed += duration
    return None


def load_eight_sleep_sessions(zip_path: Path, tz_name: str = DEFAULT_TZ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tz = ZoneInfo(tz_name)
    with ZipFile(zip_path) as archive:
        payload = json.loads(archive.read("sleep_nights.json"))
        readme = archive.read("README.md").decode("utf-8", errors="replace")
    rows = payload.get("sessions") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("Eight Sleep sleep_nights.json does not contain a sessions list.")

    sessions: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        start = parse_dt(row.get("ts"))
        stages = [stage for stage in row.get("stages") or [] if isinstance(stage, dict)]
        if start is None or not stages:
            continue
        duration_seconds = sum(float(stage.get("duration") or 0) for stage in stages)
        if duration_seconds <= 0:
            continue
        end = start + timedelta(seconds=duration_seconds)
        stage_seconds: Counter[str] = Counter()
        for stage in stages:
            stage_seconds[str(stage.get("stage") or "unknown").lower()] += float(stage.get("duration") or 0)

        timeseries = row.get("timeseries") or {}
        hr = series_stats(timeseries.get("heartRate") or [])
        hrv = series_stats(timeseries.get("hrv") or [])
        rr = series_stats(timeseries.get("respiratoryRate") or [])
        tnt = timeseries.get("tnt") or []

        sessions.append(
            {
                "session_index": idx,
                "start": start,
                "end": end,
                "wake_date": local_date(end, tz).isoformat(),
                "duration_h": duration_seconds / 3600,
                "sleep_stage_h": sum(stage_seconds[stage] for stage in SLEEP_STAGES) / 3600,
                "out_h": stage_seconds["out"] / 3600,
                "awake_h": stage_seconds["awake"] / 3600,
                "light_h": stage_seconds["light"] / 3600,
                "deep_h": stage_seconds["deep"] / 3600,
                "rem_h": stage_seconds["rem"] / 3600,
                "first_non_out": first_stage_time(start, stages, exclude_out=True),
                "first_sleep_like": first_stage_time(start, stages, SLEEP_STAGES),
                "heart_rate_median": hr["median"],
                "heart_rate_mean": hr["mean"],
                "hrv_median": hrv["median"],
                "hrv_mean": hrv["mean"],
                "respiratory_rate_median": rr["median"],
                "respiratory_rate_mean": rr["mean"],
                "heart_rate_samples": hr["count"],
                "hrv_samples": hrv["count"],
                "respiratory_rate_samples": rr["count"],
                "toss_turn_count": sum(1 for item in tnt if isinstance(item, list) and len(item) >= 2 and item[1]),
            }
        )

    metadata = {
        "session_count": len(sessions),
        "readme_mentions_side_or_occupancy": any(term in readme.lower() for term in ("side", "occupancy", "occupying", "user")),
        "top_level_session_keys": sorted({key for row in rows if isinstance(row, dict) for key in row.keys()}),
    }
    return sessions, metadata


def select_main_eight_sessions(sessions: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    by_wake: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for session in sessions:
        by_wake[session["wake_date"]].append(session)

    selected: dict[str, dict[str, Any]] = {}
    for wake_date, day_sessions in by_wake.items():
        eligible = [session for session in day_sessions if session["duration_h"] >= 3]
        if eligible:
            selected[wake_date] = max(eligible, key=lambda item: (item["duration_h"], item["sleep_stage_h"]))

    audit_rows: list[dict[str, Any]] = []
    for session in sorted(sessions, key=lambda item: (item["wake_date"], item["start"])):
        reasons = []
        session["same_wake_date_session_count"] = len(by_wake[session["wake_date"]])
        if session["duration_h"] < 3:
            reasons.append("short_lt_3h")
        if session["duration_h"] > 14:
            reasons.append("long_gt_14h")
        same_day_count = session["same_wake_date_session_count"]
        if same_day_count > 1:
            reasons.append("multi_session_wake_date")
        audit_rows.append(
            {
                **session,
                "same_wake_date_session_count": same_day_count,
                "selected_main": selected.get(session["wake_date"]) is session,
                "audit_flags": "; ".join(reasons),
            }
        )
    return selected, audit_rows


def sqlite_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return {}


def load_whoop_main_sleeps(db_path: Path, tz_name: str = DEFAULT_TZ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    tz = ZoneInfo(tz_name)
    with sqlite_ro(db_path) as con:
        sleep_rows = con.execute(
            """
            select id, observed_start, observed_end, payload_json
            from raw_events
            where provider = 'whoop' and permissions_scope = 'sleep'
            order by observed_start
            """
        ).fetchall()
        recovery_rows = con.execute(
            """
            select payload_json
            from raw_events
            where provider = 'whoop' and permissions_scope = 'recovery'
            """
        ).fetchall()

    recovery_by_cycle: dict[str, dict[str, Any]] = {}
    recovery_by_sleep: dict[str, dict[str, Any]] = {}
    for row in recovery_rows:
        payload = json_payload(row["payload_json"])
        score = payload.get("score") or {}
        recovery = {
            "resting_hr": score.get("resting_heart_rate"),
            "hrv_ms": score.get("hrv_rmssd_milli"),
        }
        if payload.get("cycle_id") is not None:
            recovery_by_cycle[str(payload["cycle_id"])] = recovery
        if payload.get("sleep_id") is not None:
            recovery_by_sleep[str(payload["sleep_id"])] = recovery

    sleeps: list[dict[str, Any]] = []
    for row in sleep_rows:
        payload = json_payload(row["payload_json"])
        start = parse_dt(payload.get("start") or row["observed_start"])
        end = parse_dt(payload.get("end") or row["observed_end"])
        if start is None or end is None or end <= start:
            continue
        score = payload.get("score") or {}
        stage = score.get("stage_summary") or {}
        sleep_h = sum(
            value
            for value in (
                millis_to_hours(stage.get("total_light_sleep_time_milli")),
                millis_to_hours(stage.get("total_slow_wave_sleep_time_milli")),
                millis_to_hours(stage.get("total_rem_sleep_time_milli")),
            )
            if value is not None
        )
        if sleep_h == 0 and stage.get("total_in_bed_time_milli") is not None:
            sleep_h = max(
                0.0,
                (millis_to_hours(stage.get("total_in_bed_time_milli")) or 0)
                - (millis_to_hours(stage.get("total_awake_time_milli")) or 0)
                - (millis_to_hours(stage.get("total_no_data_time_milli")) or 0),
            )
        recovery = recovery_by_cycle.get(str(payload.get("cycle_id"))) or recovery_by_sleep.get(str(payload.get("id"))) or {}
        sleeps.append(
            {
                "raw_event_id": row["id"],
                "start": start,
                "end": end,
                "wake_date": local_date(end, tz).isoformat(),
                "interval_h": (end - start).total_seconds() / 3600,
                "sleep_duration_h": sleep_h or None,
                "nap": bool(payload.get("nap")),
                "score_state": payload.get("score_state"),
                "sleep_efficiency": score.get("sleep_efficiency_percentage"),
                "respiratory_rate": score.get("respiratory_rate"),
                "total_in_bed_h": millis_to_hours(stage.get("total_in_bed_time_milli")),
                "awake_h": millis_to_hours(stage.get("total_awake_time_milli")),
                "no_data_h": millis_to_hours(stage.get("total_no_data_time_milli")),
                "light_h": millis_to_hours(stage.get("total_light_sleep_time_milli")),
                "deep_h": millis_to_hours(stage.get("total_slow_wave_sleep_time_milli")),
                "rem_h": millis_to_hours(stage.get("total_rem_sleep_time_milli")),
                "resting_hr": recovery.get("resting_hr"),
                "hrv_ms": recovery.get("hrv_ms"),
            }
        )

    candidates = [sleep for sleep in sleeps if not sleep["nap"] and sleep["interval_h"] >= 3 and sleep["score_state"] != "UNSCORABLE"]
    by_wake: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sleep in candidates:
        by_wake[sleep["wake_date"]].append(sleep)
    selected = {
        wake_date: max(day_sleeps, key=lambda item: (item["sleep_duration_h"] or 0, item["interval_h"]))
        for wake_date, day_sleeps in by_wake.items()
    }
    metadata = {
        "raw_sleep_count": len(sleeps),
        "main_sleep_wake_dates": len(selected),
        "first_wake_date": min(selected) if selected else None,
        "last_wake_date": max(selected) if selected else None,
    }
    return selected, metadata


def load_oura_availability(db_path: Path) -> list[dict[str, Any]]:
    with sqlite_ro(db_path) as con:
        return [
            dict(row)
            for row in con.execute(
                """
                select provider, source, metric_name, count(*) as count, min(observed_start) as first_observed, max(observed_start) as last_observed
                from normalized_metrics
                where (lower(provider) = 'oura' or lower(source) = 'oura')
                  and metric_name in ('sleep_duration', 'hrv', 'resting_hr', 'respiratory_rate', 'sleep_efficiency')
                group by provider, source, metric_name
                order by metric_name, provider, source
                """
            ).fetchall()
        ]


def interval_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> tuple[float, float]:
    overlap = max(0.0, (min(a_end, b_end) - max(a_start, b_start)).total_seconds() / 3600)
    union = max(a_end, b_end) - min(a_start, b_start)
    union_h = union.total_seconds() / 3600
    return overlap, overlap / union_h if union_h else 0


def in_family_window(dt: datetime | None, tz: ZoneInfo) -> bool:
    if dt is None:
        return False
    local_t = dt.astimezone(tz).time()
    return FAMILY_WINDOW_START <= local_t <= FAMILY_WINDOW_END


def compare_sources(eight_by_wake: dict[str, dict[str, Any]], whoop_by_wake: dict[str, dict[str, Any]], tz_name: str = DEFAULT_TZ) -> list[dict[str, Any]]:
    tz = ZoneInfo(tz_name)
    rows: list[dict[str, Any]] = []
    for wake_date in sorted(set(eight_by_wake) & set(whoop_by_wake)):
        eight = eight_by_wake[wake_date]
        whoop = whoop_by_wake[wake_date]
        overlap_h, overlap_share = interval_overlap(eight["start"], eight["end"], whoop["start"], whoop["end"])

        start_delta = (eight["start"] - whoop["start"]).total_seconds() / 60
        non_out_delta = (eight["first_non_out"] - whoop["start"]).total_seconds() / 60 if eight["first_non_out"] else None
        sleep_like_delta = (eight["first_sleep_like"] - whoop["start"]).total_seconds() / 60 if eight["first_sleep_like"] else None
        end_delta = (eight["end"] - whoop["end"]).total_seconds() / 60
        interval_delta = (eight["duration_h"] - whoop["interval_h"]) * 60
        sleep_duration_delta = (eight["sleep_stage_h"] - whoop["sleep_duration_h"]) * 60 if whoop["sleep_duration_h"] is not None else None
        rr_delta = (
            eight["respiratory_rate_median"] - float(whoop["respiratory_rate"])
            if eight["respiratory_rate_median"] is not None and whoop["respiratory_rate"] is not None
            else None
        )
        hrv_delta = (
            eight["hrv_median"] - float(whoop["hrv_ms"])
            if eight["hrv_median"] is not None and whoop["hrv_ms"] is not None
            else None
        )
        hr_delta = (
            eight["heart_rate_median"] - float(whoop["resting_hr"])
            if eight["heart_rate_median"] is not None and whoop["resting_hr"] is not None
            else None
        )

        flags: list[str] = []
        if start_delta <= -90:
            flags.append("Eight Sleep starts >=90 min before WHOOP")
        elif start_delta <= -60:
            flags.append("Eight Sleep starts 60-89 min before WHOOP")
        if non_out_delta is not None and non_out_delta <= -60:
            flags.append("Eight Sleep first non-out stage >=60 min before WHOOP")
        if sleep_like_delta is not None and sleep_like_delta <= -60:
            flags.append("Eight Sleep first sleep-like stage >=60 min before WHOOP")
        if interval_delta >= 90:
            flags.append("Eight Sleep interval >=90 min longer")
        if sleep_duration_delta is not None and sleep_duration_delta >= 90:
            flags.append("Eight Sleep sleep-stage duration >=90 min longer")
        if abs(end_delta) >= 45:
            flags.append("Wake/end differs >=45 min")
        if in_family_window(eight["start"], tz) or in_family_window(eight["first_non_out"], tz):
            flags.append("Eight Sleep starts in 18:30-20:00 family-bed window")
        if eight.get("same_wake_date_session_count", 1) > 1:
            flags.append("Multiple Eight Sleep sessions on wake date")
        if eight["duration_h"] > 14:
            flags.append("Eight Sleep session >14h")
        if rr_delta is not None and abs(rr_delta) >= 2:
            flags.append("Respiratory-rate delta >=2 breaths/min")
        if hrv_delta is not None and abs(hrv_delta) >= 20:
            flags.append("HRV delta >=20 ms")
        if hr_delta is not None and abs(hr_delta) >= 10:
            flags.append("Sleep HR vs WHOOP RHR delta >=10 bpm")

        if start_delta <= -90 and interval_delta >= 90 and abs(end_delta) < 45:
            interpretation = "strong bed-occupancy signal"
        elif start_delta <= -60 or interval_delta >= 90:
            interpretation = "possible bed-occupancy signal"
        elif abs(end_delta) >= 45:
            interpretation = "wake-time discordance"
        else:
            interpretation = "close/moderate"

        rows.append(
            {
                "wake_date": wake_date,
                "eight_start": eight["start"],
                "eight_first_non_out": eight["first_non_out"],
                "eight_first_sleep_like": eight["first_sleep_like"],
                "eight_end": eight["end"],
                "whoop_start": whoop["start"],
                "whoop_end": whoop["end"],
                "eight_interval_h": eight["duration_h"],
                "eight_sleep_stage_h": eight["sleep_stage_h"],
                "eight_out_h": eight["out_h"],
                "eight_awake_h": eight["awake_h"],
                "whoop_interval_h": whoop["interval_h"],
                "whoop_sleep_duration_h": whoop["sleep_duration_h"],
                "whoop_sleep_efficiency": whoop["sleep_efficiency"],
                "whoop_awake_h": whoop["awake_h"],
                "start_delta_min": start_delta,
                "first_non_out_delta_min": non_out_delta,
                "first_sleep_like_delta_min": sleep_like_delta,
                "end_delta_min": end_delta,
                "interval_delta_min": interval_delta,
                "sleep_duration_delta_min": sleep_duration_delta,
                "overlap_h": overlap_h,
                "overlap_share_of_union": overlap_share,
                "eight_hr_median": eight["heart_rate_median"],
                "whoop_resting_hr": whoop["resting_hr"],
                "hr_delta_bpm": hr_delta,
                "eight_hrv_median": eight["hrv_median"],
                "whoop_hrv_ms": whoop["hrv_ms"],
                "hrv_delta_ms": hrv_delta,
                "eight_respiratory_rate_median": eight["respiratory_rate_median"],
                "whoop_respiratory_rate": whoop["respiratory_rate"],
                "respiratory_rate_delta": rr_delta,
                "eight_toss_turn_count": eight["toss_turn_count"],
                "eight_same_wake_date_session_count": eight.get("same_wake_date_session_count", 1),
                "flag_count": len(flags),
                "flags": "; ".join(flags) if flags else "none",
                "interpretation": interpretation,
            }
        )
    return rows


def summarize(rows: list[dict[str, Any]], recent_start: str | None = None) -> dict[str, Any]:
    def summarize_subset(subset: list[dict[str, Any]]) -> dict[str, Any]:
        if not subset:
            return {"n": 0}
        start_deltas = [row["start_delta_min"] for row in subset]
        sleep_like_deltas = [row["first_sleep_like_delta_min"] for row in subset if row["first_sleep_like_delta_min"] is not None]
        interval_deltas = [row["interval_delta_min"] for row in subset]
        sleep_duration_deltas = [row["sleep_duration_delta_min"] for row in subset if row["sleep_duration_delta_min"] is not None]
        overlap_shares = [row["overlap_share_of_union"] for row in subset]
        return {
            "n": len(subset),
            "first_wake_date": subset[0]["wake_date"],
            "last_wake_date": subset[-1]["wake_date"],
            "median_start_delta_min": round(median(start_deltas), 1),
            "mean_start_delta_min": round(mean(start_deltas), 1),
            "median_first_sleep_like_delta_min": round(median(sleep_like_deltas), 1) if sleep_like_deltas else None,
            "median_interval_delta_min": round(median(interval_deltas), 1),
            "median_sleep_duration_delta_min": round(median(sleep_duration_deltas), 1) if sleep_duration_deltas else None,
            "median_overlap_share": round(median(overlap_shares), 3),
            "eight_starts_60_min_earlier": sum(1 for row in subset if row["start_delta_min"] <= -60),
            "eight_starts_90_min_earlier": sum(1 for row in subset if row["start_delta_min"] <= -90),
            "first_sleep_like_60_min_earlier": sum(1 for row in subset if row["first_sleep_like_delta_min"] is not None and row["first_sleep_like_delta_min"] <= -60),
            "eight_interval_90_min_longer": sum(1 for row in subset if row["interval_delta_min"] >= 90),
            "wake_end_45_min_diff": sum(1 for row in subset if abs(row["end_delta_min"]) >= 45),
            "strong_bed_occupancy_signal": sum(1 for row in subset if row["interpretation"] == "strong bed-occupancy signal"),
            "possible_bed_occupancy_signal": sum(1 for row in subset if row["interpretation"] == "possible bed-occupancy signal"),
        }

    all_summary = summarize_subset(rows)
    recent = [row for row in rows if recent_start is None or row["wake_date"] >= recent_start]
    return {
        "all_overlap": all_summary,
        "recent_overlap": summarize_subset(recent),
        "recent_start": recent_start,
        "flag_counts": dict(Counter(flag for row in rows for flag in row["flags"].split("; ") if flag and flag != "none")),
    }


def csv_ready(value: Any, tz: ZoneInfo) -> Any:
    if isinstance(value, datetime):
        return local_stamp(value, tz)
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return value


def write_overlap_csv(path: Path, rows: list[dict[str, Any]], tz_name: str) -> None:
    tz = ZoneInfo(tz_name)
    fields = [
        "wake_date",
        "eight_start",
        "eight_first_non_out",
        "eight_first_sleep_like",
        "whoop_start",
        "start_delta_min",
        "start_delta_fmt",
        "first_sleep_like_delta_min",
        "first_sleep_like_delta_fmt",
        "eight_end",
        "whoop_end",
        "end_delta_min",
        "end_delta_fmt",
        "eight_interval_h",
        "whoop_interval_h",
        "interval_delta_min",
        "eight_sleep_stage_h",
        "whoop_sleep_duration_h",
        "sleep_duration_delta_min",
        "overlap_share_of_union",
        "eight_hr_median",
        "whoop_resting_hr",
        "hr_delta_bpm",
        "eight_hrv_median",
        "whoop_hrv_ms",
        "hrv_delta_ms",
        "eight_respiratory_rate_median",
        "whoop_respiratory_rate",
        "respiratory_rate_delta",
        "eight_toss_turn_count",
        "eight_same_wake_date_session_count",
        "flags",
        "interpretation",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            out = {field: csv_ready(row.get(field), tz) for field in fields}
            out["start_delta_fmt"] = fmt_delta_minutes(row["start_delta_min"])
            out["first_sleep_like_delta_fmt"] = fmt_delta_minutes(row["first_sleep_like_delta_min"])
            out["end_delta_fmt"] = fmt_delta_minutes(row["end_delta_min"])
            writer.writerow(out)


def write_audit_csv(path: Path, rows: list[dict[str, Any]], tz_name: str) -> None:
    tz = ZoneInfo(tz_name)
    fields = [
        "wake_date",
        "session_index",
        "start",
        "first_non_out",
        "first_sleep_like",
        "end",
        "duration_h",
        "sleep_stage_h",
        "out_h",
        "awake_h",
        "light_h",
        "deep_h",
        "rem_h",
        "heart_rate_samples",
        "hrv_samples",
        "respiratory_rate_samples",
        "toss_turn_count",
        "same_wake_date_session_count",
        "selected_main",
        "audit_flags",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_ready(row.get(field), tz) for field in fields})


def json_safe(value: Any, tz: ZoneInfo) -> Any:
    if isinstance(value, datetime):
        return local_stamp(value, tz)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: json_safe(val, tz) for key, val in value.items()}
    if isinstance(value, list):
        return [json_safe(item, tz) for item in value]
    return value


def source_range(mapping: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not mapping:
        return {"wake_dates": 0, "first_wake_date": None, "last_wake_date": None}
    return {"wake_dates": len(mapping), "first_wake_date": min(mapping), "last_wake_date": max(mapping)}


def render_markdown(summary: dict[str, Any], rows: list[dict[str, Any]], paths: ArtifactPaths, tz_name: str) -> str:
    all_s = summary["comparison_summary"]["all_overlap"]
    recent_s = summary["comparison_summary"]["recent_overlap"]
    recent_start = summary["comparison_summary"]["recent_start"]
    latest = rows[-1]["wake_date"] if rows else "n/a"
    recent_rows = [row for row in rows if recent_start is None or row["wake_date"] >= recent_start]
    strongest = sorted(recent_rows or rows, key=lambda row: (row["flag_count"], -row["start_delta_min"], row["interval_delta_min"]), reverse=True)[:12]

    lines = [
        f"# Eight Sleep vs WHOOP Sleep Concordance - {summary['analysis_date']}",
        "",
        "## Executive Summary",
        "",
        f"- **Eight Sleep is now current enough for the question.** The export contains {summary['eight_sleep_export']['session_count']} parsed sessions and selected main sessions through {summary['eight_sleep_export']['selected_main_sessions']['last_wake_date']}; the matched WHOOP overlap runs through {latest}.",
        f"- **The recent signal is a bed-occupancy signal, not a clean Sam-sleep signal.** Since {recent_start}, Eight Sleep and WHOOP overlap on {recent_s.get('n', 0)} wake dates; Eight Sleep starts at least 90 minutes before WHOOP on {recent_s.get('eight_starts_90_min_earlier', 0)} of those nights, and its interval is at least 90 minutes longer on {recent_s.get('eight_interval_90_min_longer', 0)} nights.",
        f"- **Treat WHOOP as the first-pass person-level anchor.** WHOOP is worn by Sam and exposes nap flags and scored sleep bounds; Eight Sleep is a bed/side sensor and this export has no explicit side, sleeper, or occupancy identifier.",
        "- **Oura should become the adjudicator once synced.** A second person-worn source can distinguish Sam physiology from bed-level occupancy; until local Oura sleep data exists, the report keeps Oura out of the numeric comparison.",
        "",
        "## Measurement Model Grounding",
        "",
        "- **Eight Sleep:** the Pod cover tracks sleep/health from the bed, with independent sides and two separate users per Pod. Eight Sleep also describes passive detection of HR, HRV, respiratory rate, and sleep stages. Because this export exposes only `ts`, `stages`, and `timeseries`, with no side/user/occupancy field, it is safest to read Eight Sleep as bed/side context.",
        "- **WHOOP:** WHOOP uses optical PPG and algorithms to estimate heart rate continuously, with movement-artifact handling. Its API exposes sleep start/end, nap status, score state, and stage durations, so it is the cleaner person-level anchor for Sam in this comparison.",
        "- **Oura:** Oura Ring is also person-worn. It uses PPG, temperature, and accelerometer data, and Oura says its sleep staging uses movement, skin temperature, resting HR, HRV, and respiratory rate. Once your local Oura sync is complete, Oura can check whether WHOOP is the outlier or Eight Sleep is picking up someone else on the bed.",
        "",
        "## Coverage",
        "",
        f"- Eight Sleep selected main wake dates: {summary['eight_sleep_export']['selected_main_sessions']['wake_dates']} ({summary['eight_sleep_export']['selected_main_sessions']['first_wake_date']} to {summary['eight_sleep_export']['selected_main_sessions']['last_wake_date']}).",
        f"- WHOOP selected main wake dates: {summary['whoop_db']['main_sleeps']['wake_dates']} ({summary['whoop_db']['main_sleeps']['first_wake_date']} to {summary['whoop_db']['main_sleeps']['last_wake_date']}).",
        f"- Matched wake dates: {all_s.get('n', 0)} ({all_s.get('first_wake_date')} to {all_s.get('last_wake_date')}).",
        f"- Recent matched wake dates since {recent_start}: {recent_s.get('n', 0)}.",
        "",
        "## Concordance Findings",
        "",
        f"- Across all matched nights, Eight Sleep start time is a median {fmt_delta_minutes(all_s.get('median_start_delta_min'))} versus WHOOP. The median interval delta is {fmt_delta_minutes(all_s.get('median_interval_delta_min'))}.",
        f"- In the recent window, Eight Sleep start time is a median {fmt_delta_minutes(recent_s.get('median_start_delta_min'))} versus WHOOP. The median interval delta is {fmt_delta_minutes(recent_s.get('median_interval_delta_min'))}.",
        f"- Recent first sleep-like stage timing is a median {fmt_delta_minutes(recent_s.get('median_first_sleep_like_delta_min'))} versus WHOOP, which matters because Eight Sleep session start can include `out` or awake bed-presence time.",
        f"- Recent strong bed-occupancy signals: {recent_s.get('strong_bed_occupancy_signal', 0)} nights. Possible bed-occupancy signals: {recent_s.get('possible_bed_occupancy_signal', 0)} nights.",
        "",
        "## Most Relevant Recent Nights",
        "",
        "| Wake date | Eight start | Eight first sleep-like | WHOOP start | Start delta | Interval delta | End delta | Interpretation | Flags |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in strongest:
        lines.append(
            "| "
            + " | ".join(
                [
                    row["wake_date"],
                    local_stamp(row["eight_start"], ZoneInfo(tz_name)),
                    local_stamp(row["eight_first_sleep_like"], ZoneInfo(tz_name)),
                    local_stamp(row["whoop_start"], ZoneInfo(tz_name)),
                    fmt_delta_minutes(row["start_delta_min"]),
                    fmt_delta_minutes(row["interval_delta_min"]),
                    fmt_delta_minutes(row["end_delta_min"]),
                    row["interpretation"],
                    row["flags"],
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Interpretation For The Shared-Bed Setup",
            "",
            "The current pattern is consistent with Eight Sleep seeing bed or side occupancy before WHOOP sees Sam asleep. In your described routine, that could be Catherine, your older daughter sleeping between you, or your daughter being close enough to your side of the bed to influence the pressure/vibration signal. The export cannot prove which person generated a given signal, so the analysis should avoid assigning those early intervals to Sam.",
            "",
            "The strongest signal is the combination of: Eight Sleep starts much earlier, WHOOP starts later, and wake/end times are relatively close. That shape says the bed was active before Sam's wearable sleep began, then both systems converge around the morning wake period.",
            "",
            "Physiology differences are secondary. Eight Sleep HR/HRV/respiration are useful context, but the sensors and sampling windows differ from WHOOP. Large deltas are best treated as signal-mixing or different-measurement-window clues unless Oura confirms the same Sam-worn trend.",
            "",
            "## How This Improves The Analysis",
            "",
            "1. Keep `sleep_duration` for Sam anchored to WHOOP until Oura gives a second person-worn comparator.",
            "2. Add an Eight Sleep `bed_occupancy_context` interpretation layer rather than letting Eight Sleep overwrite person-level sleep.",
            "3. Use `first_sleep_like` and `first_non_out` timing, not just Eight Sleep `ts`, when checking possible child/partner pickup.",
            "4. Promote nights with early Eight Sleep start plus close wake time into a manual review queue.",
            "5. Once Oura has several nights of overlap, compare WHOOP vs Oura first; then interpret Eight Sleep disagreement against that wearable consensus.",
            "",
            "## Oura Availability",
            "",
        ]
    )
    if summary["oura_local_availability"]:
        lines.append("- Local Oura rows were found, but this first pass did not include them in numeric concordance unless they already overlapped the sleep window cleanly.")
        for item in summary["oura_local_availability"]:
            lines.append(f"- {item['provider']} / {item['source']} / {item['metric_name']}: {item['count']} rows, latest {item['last_observed']}.")
    else:
        lines.append("- No local Oura sleep/recovery rows were available in the live database for this comparison.")
    lines.extend(
        [
            "",
            "## Caveats",
            "",
            "- Eight Sleep is not being dismissed; it is being used for the thing this export can support: bed/side context.",
            "- The export does not expose explicit side, sleeper, child/partner occupancy, or confidence labels.",
            "- Sleep-stage agreement is exploratory. None of these systems is a clinical polysomnography record.",
            "- This report is not medical advice and should not be used for dosing or treatment decisions.",
            "",
            "## Artifacts",
            "",
            f"- Overlap CSV: `{paths.overlap_csv}`",
            f"- Session audit CSV: `{paths.audit_csv}`",
            f"- Summary JSON: `{paths.summary_json}`",
            "",
            "## Public Sources Used",
            "",
        ]
    )
    for item in MEASUREMENT_MODEL:
        lines.append(f"- {item['source']}: " + ", ".join(item["urls"]))
    return "\n".join(lines) + "\n"


def artifact_paths(out_dir: Path, stamp: str) -> ArtifactPaths:
    return ArtifactPaths(
        report=out_dir / f"eight_sleep_whoop_concordance_{stamp}.md",
        overlap_csv=out_dir / f"eight_sleep_whoop_overlap_{stamp}.csv",
        audit_csv=out_dir / f"eight_sleep_session_audit_{stamp}.csv",
        summary_json=out_dir / f"eight_sleep_whoop_summary_{stamp}.json",
    )


def build_artifacts(zip_path: Path, whoop_db: Path, out_dir: Path, tz_name: str = DEFAULT_TZ, analysis_date: str | None = None) -> ArtifactPaths:
    tz = ZoneInfo(tz_name)
    stamp = analysis_date or datetime.now(tz).date().isoformat()
    recent_start = (date.fromisoformat(stamp) - timedelta(days=30)).isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    eight_sessions, eight_metadata = load_eight_sleep_sessions(zip_path, tz_name)
    eight_selected, eight_audit = select_main_eight_sessions(eight_sessions)
    whoop_selected, whoop_metadata = load_whoop_main_sleeps(whoop_db, tz_name)
    oura_availability = load_oura_availability(whoop_db)
    rows = compare_sources(eight_selected, whoop_selected, tz_name)
    comparison_summary = summarize(rows, recent_start)
    paths = artifact_paths(out_dir, stamp)

    summary = {
        "analysis_date": stamp,
        "timezone": tz_name,
        "inputs": {"eight_sleep_zip": str(zip_path), "whoop_db": str(whoop_db)},
        "measurement_model": MEASUREMENT_MODEL,
        "eight_sleep_export": {
            **eight_metadata,
            "selected_main_sessions": source_range(eight_selected),
            "explicit_side_user_occupancy_fields": [],
        },
        "whoop_db": {"raw_sleep_count": whoop_metadata["raw_sleep_count"], "main_sleeps": source_range(whoop_selected)},
        "oura_local_availability": oura_availability,
        "comparison_summary": comparison_summary,
        "privacy_boundaries": [
            "Raw Eight Sleep profile fields were not written to outputs.",
            "Raw provider payloads, provider IDs, tokens, and payload hashes were not written to outputs.",
            "The live WHOOP database was opened read-only.",
        ],
    }

    write_overlap_csv(paths.overlap_csv, rows, tz_name)
    write_audit_csv(paths.audit_csv, eight_audit, tz_name)
    paths.summary_json.write_text(json.dumps(json_safe(summary, tz), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths.report.write_text(render_markdown(summary, rows, paths, tz_name), encoding="utf-8")
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a read-only Eight Sleep vs WHOOP sleep concordance report.")
    parser.add_argument("--eight-sleep-zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--whoop-db", type=Path, default=DEFAULT_WHOOP_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--timezone", default=DEFAULT_TZ)
    parser.add_argument("--analysis-date", default=None, help="Date stamp for output files, default local today.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = build_artifacts(args.eight_sleep_zip, args.whoop_db, args.out, args.timezone, args.analysis_date)
    print(f"Wrote {paths.report}")
    print(f"Wrote {paths.overlap_csv}")
    print(f"Wrote {paths.audit_csv}")
    print(f"Wrote {paths.summary_json}")


if __name__ == "__main__":
    main()
