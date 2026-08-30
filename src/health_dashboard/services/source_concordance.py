from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import combinations
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from health_dashboard.models import NormalizedMetric
from health_dashboard.services.time import local_date


WEARABLE_SLEEP_SOURCES = {"WHOOP", "Oura"}


def source_family(provider: str, source: str | None) -> str:
    combined = f"{provider} {source or ''}".lower()
    if "whoop" in combined:
        return "WHOOP"
    if "oura" in combined:
        return "Oura"
    if "eight" in combined:
        return "Eight Sleep"
    if "apple" in combined or "watch" in combined:
        return "Apple Watch"
    return source or provider


def build_source_concordance_report(db: Session, *, days: int = 90, tz_name: str = "Australia/Sydney") -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    hrv_rows = list(
        db.scalars(
            select(NormalizedMetric)
            .where(NormalizedMetric.metric_name == "hrv", NormalizedMetric.value_numeric.is_not(None), NormalizedMetric.observed_start >= cutoff)
            .order_by(NormalizedMetric.observed_start, NormalizedMetric.created_at)
        )
    )
    sleep_rows = list(
        db.scalars(
            select(NormalizedMetric)
            .where(NormalizedMetric.metric_name == "sleep_duration", NormalizedMetric.value_numeric.is_not(None), NormalizedMetric.observed_start >= cutoff)
            .order_by(NormalizedMetric.observed_start, NormalizedMetric.created_at)
        )
    )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "hrv": hrv_concordance(hrv_rows, tz_name),
        "sleep": sleep_concordance(sleep_rows, tz_name),
        "source_freshness": source_freshness(hrv_rows + sleep_rows),
        "boundaries": [
            "Eight Sleep is treated as bed-level context unless a source export identifies Sam's side or occupancy.",
            "Concordance is exploratory and is not medical advice.",
        ],
    }
    return report


def hrv_concordance(rows: list[NormalizedMetric], tz_name: str) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str], NormalizedMetric] = {}
    for row in rows:
        day = local_date(row.observed_start, tz_name).isoformat()
        source = source_family(row.provider, row.source)
        key = (day, source)
        previous = latest.get(key)
        if previous is None or row.created_at >= previous.created_at:
            latest[key] = row

    by_day: dict[str, dict[str, float]] = {}
    for (day, source), row in latest.items():
        by_day.setdefault(day, {})[source] = float(row.value_numeric or 0)

    entries: list[dict[str, Any]] = []
    for day, sources in sorted(by_day.items()):
        if len(sources) < 2:
            continue
        pairs = [
            {"a": a, "b": b, "delta_ms": round(sources[a] - sources[b], 2)}
            for a, b in combinations(sorted(sources), 2)
        ]
        entries.append(
            {
                "date": day,
                "sources": {source: round(value, 2) for source, value in sorted(sources.items())},
                "max_delta_ms": round(max(sources.values()) - min(sources.values()), 2),
                "pairs": pairs,
            }
        )
    return entries


def sleep_concordance(rows: list[NormalizedMetric], tz_name: str) -> dict[str, Any]:
    sessions: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        source = source_family(row.provider, row.source)
        if source not in {"WHOOP", "Oura", "Eight Sleep"}:
            continue
        start = row.observed_start
        end = row.observed_end or start + timedelta(hours=float(row.value_numeric or 0))
        wake_day = local_date(end, tz_name).isoformat()
        duration_h = float(row.value_numeric or 0)
        key = (wake_day, source)
        previous = sessions.get(key)
        if previous is None or duration_h > previous["duration_h"] or row.created_at >= previous["created_at"]:
            sessions[key] = {
                "source": source,
                "start": start,
                "end": end,
                "duration_h": duration_h,
                "created_at": row.created_at,
            }

    by_day: dict[str, dict[str, dict[str, Any]]] = {}
    for (day, source), session in sessions.items():
        by_day.setdefault(day, {})[source] = session

    comparisons: list[dict[str, Any]] = []
    bed_flags: list[dict[str, Any]] = []
    for day, source_sessions in sorted(by_day.items()):
        if len(source_sessions) < 2:
            continue
        entry = {
            "wake_date": day,
            "sources": {
                source: {
                    "start": session["start"].isoformat(),
                    "end": session["end"].isoformat(),
                    "duration_h": round(session["duration_h"], 2),
                }
                for source, session in sorted(source_sessions.items())
            },
        }
        comparisons.append(entry)

        eight = source_sessions.get("Eight Sleep")
        wearables = [session for source, session in source_sessions.items() if source in WEARABLE_SLEEP_SOURCES]
        if eight and wearables:
            consensus_start = average_datetime([session["start"] for session in wearables])
            consensus_end = average_datetime([session["end"] for session in wearables])
            consensus_duration = mean(session["duration_h"] for session in wearables)
            start_delta_min = (aware_utc(eight["start"]) - consensus_start).total_seconds() / 60
            end_delta_min = (aware_utc(eight["end"]) - consensus_end).total_seconds() / 60
            duration_delta_min = (eight["duration_h"] - consensus_duration) * 60
            reasons = []
            if abs(start_delta_min) >= 60:
                reasons.append("Eight Sleep start differs from wearable consensus by >=60 min")
            if abs(end_delta_min) >= 45:
                reasons.append("Eight Sleep wake/end differs from wearable consensus by >=45 min")
            if abs(duration_delta_min) >= 90:
                reasons.append("Eight Sleep duration differs from wearable consensus by >=90 min")
            if reasons:
                bed_flags.append(
                    {
                        "wake_date": day,
                        "start_delta_min": round(start_delta_min),
                        "end_delta_min": round(end_delta_min),
                        "duration_delta_min": round(duration_delta_min),
                        "reasons": reasons,
                    }
                )

    return {"comparisons": comparisons, "bed_sharing_flags": bed_flags}


def average_datetime(values: list[datetime]) -> datetime:
    timestamps = [aware_utc(value).timestamp() for value in values]
    return datetime.fromtimestamp(mean(timestamps), tz=timezone.utc)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def source_freshness(rows: list[NormalizedMetric]) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str], datetime] = {}
    for row in rows:
        source = source_family(row.provider, row.source)
        key = (source, row.metric_name)
        previous = latest.get(key)
        if previous is None or row.observed_start > previous:
            latest[key] = row.observed_start
    return [
        {"source": source, "metric": metric, "latest_observed": observed.isoformat()}
        for (source, metric), observed in sorted(latest.items())
    ]


def render_source_concordance_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Source Concordance Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Window: {report['window_days']} days",
        "",
        "## HRV Concordance",
    ]
    hrv = report.get("hrv") or []
    if not hrv:
        lines.append("- No same-day HRV overlap across sources in this window.")
    for item in hrv:
        sources = ", ".join(f"{source}: {value} ms" for source, value in item["sources"].items())
        lines.append(f"- {item['date']}: max delta {item['max_delta_ms']} ms ({sources})")

    lines.extend(["", "## Sleep Concordance"])
    comparisons = (report.get("sleep") or {}).get("comparisons") or []
    if not comparisons:
        lines.append("- No same-wake-date sleep overlap across WHOOP, Oura, and Eight Sleep in this window.")
    for item in comparisons:
        sources = ", ".join(f"{source}: {values['duration_h']} h" for source, values in item["sources"].items())
        lines.append(f"- {item['wake_date']}: {sources}")

    lines.extend(["", "## Bed-Level Flags"])
    flags = (report.get("sleep") or {}).get("bed_sharing_flags") or []
    if not flags:
        lines.append("- No Eight Sleep bed-level timing flags in this window.")
    for item in flags:
        reasons = "; ".join(item["reasons"])
        lines.append(
            f"- {item['wake_date']}: start {item['start_delta_min']} min, end {item['end_delta_min']} min, duration {item['duration_delta_min']} min. {reasons}."
        )

    lines.extend(["", "## Source Freshness"])
    for item in report.get("source_freshness") or []:
        lines.append(f"- {item['source']} / {item['metric']}: {item['latest_observed']}")

    lines.extend(["", "## Boundaries"])
    lines.extend(f"- {item}" for item in report.get("boundaries") or [])
    return "\n".join(lines) + "\n"
