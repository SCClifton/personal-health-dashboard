from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import combinations
from statistics import mean, median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from health_dashboard.models import ConnectorState, NormalizedMetric, OAuthToken, RawEvent
from health_dashboard.services.time import local_date


WEARABLE_SLEEP_SOURCES = {"WHOOP", "Oura"}
DAILY_COMPARISON_METRICS = {
    "steps": "count",
    "resting_hr": "bpm",
    "active_energy": "kcal",
    "systolic_bp": "mmHg",
    "diastolic_bp": "mmHg",
}
DIRECT_API_PROVIDERS = {"oura", "whoop", "strava"}
APPLE_HEALTH_PROVIDERS = {"apple_health", "health_auto_export", "health_auto_export_mcp"}


def source_family(provider: str, source: str | None) -> str:
    provider_key = provider.lower()
    source_text = (source or "").lower()
    if provider_key in APPLE_HEALTH_PROVIDERS:
        if "|" in source_text:
            return "Mixed Apple Health Sources"
        detected: list[str] = []
        if "whoop" in source_text:
            detected.append("WHOOP")
        if "oura" in source_text:
            detected.append("Oura")
        if "eight" in source_text:
            detected.append("Eight Sleep")
        if "hilo" in source_text or "aktiia" in source_text:
            detected.append("Hilo")
        if "watch" in source_text:
            detected.append("Apple Watch")
        if len(detected) > 1:
            return "Mixed Apple Health Sources"
        if detected:
            return detected[0]
        return source or "Apple Health"

    combined = f"{provider} {source or ''}".lower()
    if "whoop" in combined:
        return "WHOOP"
    if "oura" in combined:
        return "Oura"
    if "eight" in combined:
        return "Eight Sleep"
    if "hilo" in combined or "aktiia" in combined:
        return "Hilo"
    if "apple" in combined or "watch" in combined:
        return "Apple Watch"
    return source or provider


def source_route(provider: str) -> str:
    provider_key = provider.lower()
    if provider_key in DIRECT_API_PROVIDERS:
        return "direct_api"
    if provider_key in APPLE_HEALTH_PROVIDERS:
        return "apple_health_relay"
    if provider_key in {"bp", "weight", "nutrition"} or "csv" in provider_key:
        return "local_import"
    return "local_connector"


def _source_priority(row: NormalizedMetric) -> tuple[int, datetime]:
    priority = {"direct_api": 3, "local_connector": 2, "local_import": 2, "apple_health_relay": 1}
    return priority[source_route(row.provider)], row.created_at


def build_source_concordance_report(db: Session, *, days: int = 90, tz_name: str = "Australia/Sydney") -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = list(
        db.scalars(
            select(NormalizedMetric)
            .where(NormalizedMetric.observed_start >= cutoff)
            .order_by(NormalizedMetric.observed_start, NormalizedMetric.created_at)
        )
    )
    numeric_rows = [row for row in rows if row.value_numeric is not None]
    hrv_rows = [row for row in numeric_rows if row.metric_name == "hrv"]
    sleep_rows = [row for row in numeric_rows if row.metric_name == "sleep_duration"]
    daily_comparisons = {
        metric: daily_metric_concordance(
            [row for row in numeric_rows if row.metric_name == metric],
            tz_name,
            unit=unit,
        )
        for metric, unit in DAILY_COMPARISON_METRICS.items()
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "provider_inventory": provider_inventory(db),
        "metric_coverage": metric_coverage(rows, tz_name),
        "hrv": hrv_concordance(hrv_rows, tz_name),
        "sleep": sleep_concordance(sleep_rows, tz_name),
        "daily_comparisons": daily_comparisons,
        "source_freshness": source_freshness(rows),
        "boundaries": [
            "Eight Sleep is treated as bed-level context unless a source export identifies Sam's side or occupancy.",
            "Direct-provider rows and Apple Health relays remain separate in the inventory; relayed labels are not proof of direct API access.",
            "An Apple Health aggregate naming multiple contributing devices is classified as Mixed Apple Health Sources and cannot be used as a device-specific comparison.",
            "WHOOP's direct API connector currently imports recovery, cycle, sleep, workout, and body-measurement collections; WHOOP-labelled steps arrive through Apple Health when present.",
            "Daily overlap measures agreement and completeness, not device accuracy; a reference method or validated wear-time evidence is required to declare a winner.",
            "Concordance is exploratory and is not medical advice.",
        ],
    }
    return report


def provider_inventory(db: Session) -> list[dict[str, Any]]:
    connector_states = {state.connector: state for state in db.scalars(select(ConnectorState))}
    oauth_providers = {token.provider for token in db.scalars(select(OAuthToken)) if token.access_token}
    providers = sorted({provider for (provider,) in db.query(RawEvent.provider).distinct().all()} | set(connector_states) | oauth_providers)
    inventory: list[dict[str, Any]] = []
    for provider in providers:
        count, first_observed, latest_observed, latest_received = (
            db.query(
                RawEvent.provider,
                func.count(RawEvent.id),
                func.min(RawEvent.observed_start),
                func.max(RawEvent.observed_start),
                func.max(RawEvent.received_at),
            )
            .filter(RawEvent.provider == provider)
            .group_by(RawEvent.provider)
            .first()
            or (provider, 0, None, None, None)
        )[1:]
        normalized_count, first_normalized, latest_normalized = (
            db.query(
                NormalizedMetric.provider,
                func.count(NormalizedMetric.id),
                func.min(NormalizedMetric.observed_start),
                func.max(NormalizedMetric.observed_start),
            )
            .filter(NormalizedMetric.provider == provider)
            .group_by(NormalizedMetric.provider)
            .first()
            or (provider, 0, None, None)
        )[1:]
        state = connector_states.get(provider)
        inventory.append(
            {
                "provider": provider,
                "route": source_route(provider),
                "oauth_authorized": provider in oauth_providers,
                "connector_status": state.status if state else None,
                "raw_records": count,
                "first_observed": first_observed.isoformat() if first_observed else None,
                "latest_observed": latest_observed.isoformat() if latest_observed else None,
                "latest_received": latest_received.isoformat() if latest_received else None,
                "normalized_metrics": normalized_count,
                "first_normalized": first_normalized.isoformat() if first_normalized else None,
                "latest_normalized": latest_normalized.isoformat() if latest_normalized else None,
            }
        )
    return inventory


def metric_coverage(rows: list[NormalizedMetric], tz_name: str) -> list[dict[str, Any]]:
    coverage: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        family = source_family(row.provider, row.source)
        route = source_route(row.provider)
        key = (family, route, row.provider, row.metric_name)
        entry = coverage.setdefault(
            key,
            {
                "source": family,
                "route": route,
                "provider": row.provider,
                "metric": row.metric_name,
                "unit": row.unit,
                "observations": 0,
                "dates": set(),
                "first_observed": row.observed_start,
                "latest_observed": row.observed_start,
            },
        )
        entry["observations"] += 1
        entry["dates"].add(local_date(row.observed_start, tz_name).isoformat())
        entry["first_observed"] = min(entry["first_observed"], row.observed_start)
        entry["latest_observed"] = max(entry["latest_observed"], row.observed_start)
        if entry["unit"] is None and row.unit is not None:
            entry["unit"] = row.unit

    result: list[dict[str, Any]] = []
    for entry in coverage.values():
        result.append(
            {
                **{key: value for key, value in entry.items() if key != "dates"},
                "days_with_data": len(entry["dates"]),
                "first_observed": entry["first_observed"].isoformat(),
                "latest_observed": entry["latest_observed"].isoformat(),
            }
        )
    return sorted(result, key=lambda item: (item["source"], item["route"], item["metric"], item["provider"]))


def daily_metric_concordance(rows: list[NormalizedMetric], tz_name: str, *, unit: str) -> dict[str, Any]:
    latest: dict[tuple[str, str], NormalizedMetric] = {}
    for row in rows:
        if row.source == "auth_probe":
            continue
        if source_route(row.provider) == "apple_health_relay" and row.observed_start.time() != datetime.min.time():
            # Health Auto Export daily totals are timestamped at midnight.
            # Intraday HealthKit samples are not comparable to daily totals.
            continue
        day = local_date(row.observed_start, tz_name).isoformat()
        family = source_family(row.provider, row.source)
        key = (day, family)
        previous = latest.get(key)
        if previous is None or _source_priority(row) >= _source_priority(previous):
            latest[key] = row

    by_day: dict[str, dict[str, NormalizedMetric]] = {}
    for (day, family), row in latest.items():
        by_day.setdefault(day, {})[family] = row

    entries: list[dict[str, Any]] = []
    pair_values: dict[tuple[str, str], list[dict[str, float]]] = {}
    for day, source_rows in sorted(by_day.items()):
        if len(source_rows) < 2:
            continue
        values = {source: float(row.value_numeric or 0) for source, row in source_rows.items()}
        pairs: list[dict[str, Any]] = []
        for a, b in combinations(sorted(values), 2):
            delta = values[a] - values[b]
            denominator = mean([abs(values[a]), abs(values[b])])
            absolute_percent_difference = abs(delta) / denominator * 100 if denominator else 0.0
            pair = {
                "a": a,
                "b": b,
                "delta": round(delta, 2),
                "absolute_percent_difference": round(absolute_percent_difference, 2),
            }
            pairs.append(pair)
            pair_values.setdefault((a, b), []).append(
                {"delta": delta, "absolute_percent_difference": absolute_percent_difference}
            )
        entries.append(
            {
                "date": day,
                "unit": unit,
                "sources": {source: round(value, 2) for source, value in sorted(values.items())},
                "routes": {source: source_route(row.provider) for source, row in sorted(source_rows.items())},
                "max_delta": round(max(values.values()) - min(values.values()), 2),
                "pairs": pairs,
            }
        )

    pair_summary = []
    for (a, b), values in sorted(pair_values.items()):
        deltas = [item["delta"] for item in values]
        percentages = [item["absolute_percent_difference"] for item in values]
        pair_summary.append(
            {
                "a": a,
                "b": b,
                "matched_days": len(values),
                "mean_delta": round(mean(deltas), 2),
                "median_absolute_delta": round(median(abs(value) for value in deltas), 2),
                "mean_absolute_percent_difference": round(mean(percentages), 2),
                "unit": unit,
            }
        )
    return {"comparisons": entries, "pair_summary": pair_summary}


def hrv_concordance(rows: list[NormalizedMetric], tz_name: str) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str], NormalizedMetric] = {}
    for row in rows:
        day = local_date(row.observed_start, tz_name).isoformat()
        source = source_family(row.provider, row.source)
        key = (day, source)
        previous = latest.get(key)
        if previous is None or _source_priority(row) >= _source_priority(previous):
            latest[key] = row

    by_day: dict[str, dict[str, NormalizedMetric]] = {}
    for (day, source), row in latest.items():
        by_day.setdefault(day, {})[source] = row

    entries: list[dict[str, Any]] = []
    for day, source_rows in sorted(by_day.items()):
        if len(source_rows) < 2:
            continue
        values = {source: float(row.value_numeric or 0) for source, row in source_rows.items()}
        pairs = [
            {"a": a, "b": b, "delta_ms": round(values[a] - values[b], 2)}
            for a, b in combinations(sorted(values), 2)
        ]
        entries.append(
            {
                "date": day,
                "sources": {source: round(value, 2) for source, value in sorted(values.items())},
                "routes": {source: source_route(row.provider) for source, row in sorted(source_rows.items())},
                "max_delta_ms": round(max(values.values()) - min(values.values()), 2),
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
        current_priority = _source_priority(row)
        if previous is None or current_priority > previous["priority"] or (
            current_priority == previous["priority"] and duration_h >= previous["duration_h"]
        ):
            sessions[key] = {
                "source": source,
                "provider": row.provider,
                "route": source_route(row.provider),
                "start": start,
                "end": end,
                "duration_h": duration_h,
                "created_at": row.created_at,
                "priority": current_priority,
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
                    "route": session["route"],
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
    latest: dict[tuple[str, str, str, str], datetime] = {}
    for row in rows:
        source = source_family(row.provider, row.source)
        route = source_route(row.provider)
        key = (source, route, row.provider, row.metric_name)
        previous = latest.get(key)
        if previous is None or row.observed_start > previous:
            latest[key] = row.observed_start
    return [
        {"source": source, "route": route, "provider": provider, "metric": metric, "latest_observed": observed.isoformat()}
        for (source, route, provider, metric), observed in sorted(latest.items())
    ]


def render_source_concordance_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Source Concordance Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Window: {report['window_days']} days",
        "",
        "## Provider Inventory",
        "",
        "| Provider | Route | OAuth | Status | Raw records | Normalized metrics | Raw observed range | Normalized range | Latest receipt |",
        "|---|---|---:|---|---:|---:|---|---|---|",
    ]
    for item in report.get("provider_inventory") or []:
        lines.append(
            "| {provider} | {route} | {oauth} | {status} | {raw_records} | {normalized_metrics} | {raw_range} | {normalized_range} | {received} |".format(
                provider=item["provider"],
                route=item["route"].replace("_", " "),
                oauth="yes" if item["oauth_authorized"] else "no",
                status=item["connector_status"] or "-",
                raw_records=item["raw_records"],
                normalized_metrics=item["normalized_metrics"],
                raw_range=f"{item['first_observed']} to {item['latest_observed']}" if item["first_observed"] else "-",
                normalized_range=f"{item['first_normalized']} to {item['latest_normalized']}" if item["first_normalized"] else "-",
                received=item["latest_received"] or "-",
            )
        )

    lines.extend(
        [
            "",
            "## Normalized Metric Coverage",
            "",
            "| Source | Route | Provider | Metric | Observations | Days | First | Latest |",
            "|---|---|---|---|---:|---:|---|---|",
        ]
    )
    coverage = report.get("metric_coverage") or []
    if not coverage:
        lines.append("| - | - | - | No normalized metrics in this window | 0 | 0 | - | - |")
    for item in coverage:
        lines.append(
            f"| {item['source']} | {item['route'].replace('_', ' ')} | {item['provider']} | {item['metric']} | "
            f"{item['observations']} | {item['days_with_data']} | {item['first_observed']} | {item['latest_observed']} |"
        )

    lines.extend([
        "",
        "## HRV Concordance",
    ])
    hrv = report.get("hrv") or []
    if not hrv:
        lines.append("- No same-day HRV overlap across sources in this window.")
    for item in hrv:
        sources = ", ".join(f"{source}: {value} ms" for source, value in item["sources"].items())
        lines.append(f"- {item['date']}: max delta {item['max_delta_ms']} ms ({sources})")

    comparison_titles = {
        "steps": "Step Concordance",
        "resting_hr": "Resting Heart Rate Concordance",
        "active_energy": "Active Energy Concordance",
        "systolic_bp": "Systolic Blood Pressure Concordance",
        "diastolic_bp": "Diastolic Blood Pressure Concordance",
    }
    for metric, title in comparison_titles.items():
        comparison = (report.get("daily_comparisons") or {}).get(metric) or {}
        lines.extend(["", f"## {title}"])
        summaries = comparison.get("pair_summary") or []
        if not summaries:
            lines.append("- No matched days across two or more sources in this window.")
        for item in summaries:
            lines.append(
                f"- {item['a']} vs {item['b']}: {item['matched_days']} matched days; "
                f"mean signed delta {item['mean_delta']} {item['unit']}; median absolute delta "
                f"{item['median_absolute_delta']} {item['unit']}; mean absolute difference "
                f"{item['mean_absolute_percent_difference']}%."
            )
        recent = (comparison.get("comparisons") or [])[-14:]
        if recent:
            lines.append("- Recent matched days:")
            for item in recent:
                sources = ", ".join(f"{source}: {value} {item['unit']}" for source, value in item["sources"].items())
                lines.append(f"  - {item['date']}: {sources}")

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
        lines.append(
            f"- {item['source']} / {item['metric']} ({item['route'].replace('_', ' ')}, {item['provider']}): {item['latest_observed']}"
        )

    lines.extend(["", "## Boundaries"])
    lines.extend(f"- {item}" for item in report.get("boundaries") or [])
    return "\n".join(lines) + "\n"
