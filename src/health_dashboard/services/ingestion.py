from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from health_dashboard.config import get_settings
from health_dashboard.models import DailyFeature, NormalizedMetric, RawEvent
from health_dashboard.services.normalization import MetricValue, metric_from_payload, source_priority
from health_dashboard.services.time import local_date, parse_datetime


DAILY_FIELDS = {
    "weight",
    "calories",
    "protein",
    "carbs",
    "fat",
    "systolic_bp",
    "diastolic_bp",
    "resting_hr",
    "hrv",
    "sleep_duration",
    "sleep_efficiency",
    "steps",
    "active_energy",
    "training_load",
    "workout_count",
    "tirzepatide_dose_mg",
}


def payload_hash(payload: dict[str, Any] | list[Any] | bytes) -> str:
    if isinstance(payload, bytes):
        data = payload
    else:
        data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def source_record_id_from_payload(payload: dict[str, Any]) -> str | None:
    for key in ("id", "uuid", "source_record_id", "record_id", "external_id"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def observed_start_from_payload(payload: dict[str, Any]) -> datetime | None:
    return parse_datetime(
        payload.get("observed_start")
        or payload.get("startDate")
        or payload.get("start")
        or payload.get("start_date")
        or payload.get("start_date_local")
        or payload.get("date")
        or payload.get("start_time")
    )


def observed_end_from_payload(payload: dict[str, Any]) -> datetime | None:
    return parse_datetime(payload.get("observed_end") or payload.get("endDate") or payload.get("end") or payload.get("end_date") or payload.get("end_time"))


def store_raw_event(
    db: Session,
    *,
    provider: str,
    payload: dict[str, Any],
    import_batch_id: str | None = None,
    source_record_id: str | None = None,
    permissions_scope: str | None = None,
    schema_version: str = "1",
    metrics: Iterable[MetricValue] | None = None,
) -> tuple[RawEvent, bool]:
    record_id = source_record_id or source_record_id_from_payload(payload)
    hashed = payload_hash(payload)
    duplicate_query = select(RawEvent).where(RawEvent.provider == provider)
    if record_id:
        duplicate_query = duplicate_query.where(RawEvent.source_record_id == record_id)
    else:
        duplicate_query = duplicate_query.where(RawEvent.payload_hash == hashed)
    existing = db.scalar(duplicate_query)
    if existing:
        return existing, False

    raw_event = RawEvent(
        provider=provider,
        source_record_id=record_id,
        import_batch_id=import_batch_id or str(uuid4()),
        observed_start=observed_start_from_payload(payload),
        observed_end=observed_end_from_payload(payload),
        payload_json=payload,
        payload_hash=hashed,
        permissions_scope=permissions_scope,
        schema_version=schema_version,
    )
    db.add(raw_event)
    db.flush()

    generated_metrics = list(metrics) if metrics is not None else []
    if not generated_metrics:
        maybe_metric = metric_from_payload(provider, payload)
        if maybe_metric:
            generated_metrics.append(maybe_metric)
    for metric in generated_metrics:
        db.add(
            NormalizedMetric(
                provider=provider,
                source=metric.source or provider,
                metric_name=metric.metric_name,
                value_numeric=metric.value_numeric,
                value_text=metric.value_text,
                unit=metric.unit,
                observed_start=metric.observed_start,
                observed_end=metric.observed_end,
                aggregation_window=metric.aggregation_window,
                confidence=metric.confidence,
                raw_event_id=raw_event.id,
            )
        )
    db.flush()
    return raw_event, True


def rebuild_daily_features(db: Session, start: date | None = None, end: date | None = None, tz_name: str | None = None) -> None:
    settings = get_settings()
    tz = tz_name or settings.local_timezone
    metric_query = select(NormalizedMetric)
    if start:
        metric_query = metric_query.where(NormalizedMetric.observed_start >= datetime.combine(start, datetime.min.time()))
    if end:
        metric_query = metric_query.where(NormalizedMetric.observed_start < datetime.combine(end + timedelta(days=1), datetime.min.time()))
    rows = list(db.scalars(metric_query))
    by_day: dict[date, list[NormalizedMetric]] = defaultdict(list)
    for row in rows:
        by_day[local_date(row.observed_start, tz)].append(row)

    for day, metrics in by_day.items():
        feature = db.get(DailyFeature, {"date": day, "timezone": tz})
        if not feature:
            feature = DailyFeature(date=day, timezone=tz, source_flags={})
            db.add(feature)
        feature.source_flags = {}
        for metric_name in DAILY_FIELDS:
            candidates = daily_metric_candidates(metrics, metric_name)
            if not candidates:
                setattr(feature, metric_name, None)
                continue
            if metric_name in {"calories", "protein", "carbs", "fat"}:
                candidates = latest_metric_revisions(candidates)
                value = sum(m.value_numeric or 0 for m in candidates)
                sources = sorted({m.source for m in candidates})
            elif metric_name in {"steps", "active_energy", "training_load", "workout_count"}:
                candidates = best_source_metrics(latest_metric_revisions(candidates), metric_name)
                value = sum(m.value_numeric or 0 for m in candidates)
                sources = sorted({m.source for m in candidates})
            elif metric_name == "sleep_duration":
                grouped = sleep_duration_by_source(candidates)
                best_source, best = sorted(
                    grouped.items(),
                    key=lambda item: (source_priority(metric_name, item[0]), item[1][1], item[1][0]),
                    reverse=True,
                )[0]
                value = best[0]
                sources = [best_source]
            else:
                best = sorted(
                    candidates,
                    key=lambda m: (source_priority(metric_name, m.source), m.confidence, m.created_at),
                    reverse=True,
                )[0]
                value = best.value_numeric
                sources = [best.source]
            setattr(feature, metric_name, value)
            feature.source_flags[metric_name] = sources
            if metric_name == "tirzepatide_dose_mg":
                feature.tirzepatide_days_since_dose = 0.0
    db.flush()
    dose_days = sorted(
        day
        for day in by_day
        if (feature := db.get(DailyFeature, {"date": day, "timezone": tz})) and feature.tirzepatide_dose_mg is not None
    )
    for day in sorted(by_day):
        feature = db.get(DailyFeature, {"date": day, "timezone": tz})
        if not feature:
            continue
        prior = [dose_day for dose_day in dose_days if dose_day <= day]
        feature.tirzepatide_days_since_dose = float((day - prior[-1]).days) if prior else None
    db.flush()


def latest_metric_revisions(metrics: list[NormalizedMetric]) -> list[NormalizedMetric]:
    """Collapse repeated aggregate snapshots, keeping the latest revision of each identity."""
    latest: dict[tuple, NormalizedMetric] = {}
    for metric in metrics:
        source = (metric.source or "").lower()
        if metric.aggregation_window == "event" or source.startswith("myfitnesspal:"):
            identity = (
                metric.provider,
                metric.source,
                metric.metric_name,
                metric.observed_start,
                metric.observed_end,
                metric.aggregation_window,
                metric.unit,
                metric.raw_event_id,
            )
        else:
            identity = (
                metric.provider,
                metric.metric_name,
                metric.observed_start,
                metric.observed_end,
                metric.aggregation_window,
                metric.unit,
            )
        previous = latest.get(identity)
        if previous is None or metric.created_at >= previous.created_at:
            latest[identity] = metric
    return list(latest.values())


def daily_metric_candidates(metrics: list[NormalizedMetric], metric_name: str) -> list[NormalizedMetric]:
    candidates = [m for m in metrics if m.metric_name == metric_name and m.value_numeric is not None]
    if metric_name == "active_energy":
        candidates = [m for m in candidates if not is_whoop_cycle_energy(m)]
    return candidates


def is_whoop_cycle_energy(metric: NormalizedMetric) -> bool:
    if metric.provider != "whoop" or metric.metric_name != "active_energy":
        return False
    return metric.raw_event.permissions_scope == "cycle"


def best_source_metrics(metrics: list[NormalizedMetric], metric_name: str) -> list[NormalizedMetric]:
    """Choose one source per day for activity fields so overlapping providers do not double count."""
    if not metrics:
        return []
    grouped: dict[str, list[NormalizedMetric]] = defaultdict(list)
    for metric in metrics:
        grouped[metric.source].append(metric)
    return sorted(
        grouped.items(),
        key=lambda item: (
            max(metric_source_priority(metric_name, metric) for metric in item[1]),
            max(metric.confidence for metric in item[1]),
            max(metric.created_at for metric in item[1]),
        ),
        reverse=True,
    )[0][1]


def metric_source_priority(metric_name: str, metric: NormalizedMetric) -> int:
    return max(source_priority(metric_name, metric.provider), source_priority(metric_name, metric.source))


def sleep_duration_by_source(metrics: list[NormalizedMetric]) -> dict[str, tuple[float, float]]:
    """Return source -> (union hours, confidence), merging overlapping sleep intervals."""
    grouped: dict[str, list[NormalizedMetric]] = defaultdict(list)
    for metric in metrics:
        grouped[metric.source].append(metric)

    durations: dict[str, tuple[float, float]] = {}
    for source, source_metrics in grouped.items():
        if len(source_metrics) == 1:
            value = source_metrics[0].value_numeric or 0
        else:
            intervals = [
                (metric.observed_start, metric.observed_end)
                for metric in source_metrics
                if metric.observed_end is not None and metric.observed_end > metric.observed_start
            ]
            value = union_interval_hours(intervals) if intervals else sum(metric.value_numeric or 0 for metric in source_metrics)
        confidence = max((metric.confidence for metric in source_metrics), default=0)
        durations[source] = (value, confidence)
    return durations


def union_interval_hours(intervals: list[tuple[datetime, datetime]]) -> float:
    merged: list[list[datetime]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return sum((end - start).total_seconds() / 3600 for start, end in merged)


def daily_feature_rows(db: Session, days: int = 90) -> list[DailyFeature]:
    cutoff = date.today() - timedelta(days=days)
    return list(db.scalars(select(DailyFeature).where(DailyFeature.date >= cutoff).order_by(DailyFeature.date)))


def find_duplicate_payload(db: Session, provider: str, payload: dict[str, Any]) -> RawEvent | None:
    record_id = source_record_id_from_payload(payload)
    hashed = payload_hash(payload)
    return db.scalar(
        select(RawEvent).where(
            RawEvent.provider == provider,
            or_(RawEvent.source_record_id == record_id, and_(RawEvent.source_record_id.is_(None), RawEvent.payload_hash == hashed)),
        )
    )
