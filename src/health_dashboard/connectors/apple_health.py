from __future__ import annotations

import hashlib
import json
from typing import Any

from health_dashboard.config import Settings
from health_dashboard.connectors.base import ConnectorInfo, ConnectorStatus
from health_dashboard.services.normalization import canonical_metric_name
from health_dashboard.services.normalization import MetricValue, metric_from_payload
from health_dashboard.services.time import parse_datetime


class AppleHealthConnector:
    name = "apple_health"
    docs_url = "https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def status(self) -> ConnectorInfo:
        if self.settings.health_auto_export_shared_secret:
            status = ConnectorStatus.CONFIGURED
            next_action = "Configure Health Auto Export to POST to /ingest/apple-health with the shared secret."
        else:
            status = ConnectorStatus.MISSING_CREDENTIALS
            next_action = "Set HEALTH_AUTO_EXPORT_SHARED_SECRET in .env or load it with op."
        return ConnectorInfo(
            name=self.name,
            status=status,
            detail="Health Auto Export REST/webhook bridge for Apple Health bulk and incremental uploads.",
            next_action=next_action,
            official_docs_url=self.docs_url,
        )


def records_from_health_auto_export(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        records: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                records.extend(records_from_health_auto_export(item))
        return records
    if not isinstance(payload, dict):
        return []
    metric_records = metric_point_records_from_health_auto_export_v2(payload)
    if metric_records:
        return metric_records
    for key in ("data", "metrics", "workouts", "samples", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def metrics_from_apple_record(record: dict[str, Any]) -> list[MetricValue]:
    point_metrics = metrics_from_health_auto_export_v2_point_record(record)
    if point_metrics:
        return point_metrics

    nested_metrics = metrics_from_health_auto_export_v2(record)
    if nested_metrics:
        return nested_metrics

    maybe = metric_from_payload("apple_health", record, default_source=record.get("sourceName") or "apple_health")
    if maybe:
        return [maybe]

    metrics: list[MetricValue] = []
    observed = parse_datetime(record.get("date") or record.get("startDate") or record.get("observed_start"))
    if not observed:
        return metrics
    source = record.get("sourceName") or record.get("source") or "apple_health"
    for key, metric_name in {
        "steps": "steps",
        "activeEnergy": "active_energy",
        "active_energy": "active_energy",
        "restingHeartRate": "resting_hr",
        "heartRateVariability": "hrv",
        "sleepDuration": "sleep_duration",
        "weight": "weight",
    }.items():
        if key in record and record[key] is not None:
            nested = {
                "metric_name": metric_name,
                "value": record[key],
                "unit": record.get("unit"),
                "observed_start": observed.isoformat(),
                "observed_end": record.get("endDate"),
                "source": source,
                "confidence": 0.7,
            }
            metric = metric_from_payload("apple_health", nested, default_source=source)
            if metric:
                metrics.append(metric)
    return metrics


def metric_point_records_from_health_auto_export_v2(payload: dict[str, Any]) -> list[dict[str, Any]]:
    metrics_payload = payload.get("data", {}).get("metrics") if isinstance(payload.get("data"), dict) else None
    if not isinstance(metrics_payload, list):
        return []

    records: list[dict[str, Any]] = []
    for metric_group in metrics_payload:
        if not isinstance(metric_group, dict):
            continue
        name = metric_group.get("name")
        unit = metric_group.get("units")
        points = metric_group.get("data")
        if not name or not isinstance(points, list):
            continue
        for point in points:
            if not isinstance(point, dict):
                continue
            observed = point.get("start") or point.get("startDate") or point.get("date")
            if observed is None:
                continue
            record = {
                "id": health_auto_export_point_id(name=name, unit=unit, point=point),
                "metric_name": name,
                "unit": unit,
                "point": point,
                "health_auto_export": {"version": "v2", "data_type": "metrics"},
            }
            records.append(record)
    return records


def metrics_from_health_auto_export_v2_point_record(record: dict[str, Any]) -> list[MetricValue]:
    if not isinstance(record.get("health_auto_export"), dict):
        return []
    if record["health_auto_export"].get("version") != "v2":
        return []
    point = record.get("point")
    if not isinstance(point, dict):
        return []
    observed = point.get("start") or point.get("startDate") or point.get("date")
    if observed is None:
        return []

    name = str(record.get("metric_name") or "")
    unit = record.get("unit")
    definitions: list[tuple[str, Any, Any]] = []
    if point.get("qty") is not None:
        definitions.append((canonical_metric_name(name), point.get("qty"), point.get("end") or point.get("endDate")))
    elif name == "blood_pressure":
        definitions.extend(
            [
                ("systolic_bp", point.get("systolic"), None),
                ("diastolic_bp", point.get("diastolic"), None),
            ]
        )
    elif name == "heart_rate":
        definitions.extend(
            [
                ("heart_rate", point.get("Avg"), None),
                ("min_heart_rate", point.get("Min"), None),
                ("max_heart_rate", point.get("Max"), None),
            ]
        )
    elif name == "sleep_analysis":
        definitions.append(("sleep_duration", point.get("totalSleep"), point.get("sleepEnd")))

    metrics: list[MetricValue] = []
    for metric_name, value, observed_end in definitions:
        if value is None:
            continue
        metric = metric_from_payload(
            "apple_health",
            {
                "metric_name": metric_name,
                "value": value,
                "unit": unit,
                "observed_start": observed,
                "observed_end": observed_end,
                "source": source_name(point.get("source")),
                "confidence": 0.7,
                "aggregation_window": "health_auto_export_v2",
            },
            default_source="apple_health",
        )
        if metric:
            metrics.append(metric)
    return metrics


def health_auto_export_point_id(*, name: Any, unit: Any, point: dict[str, Any]) -> str:
    identity = {
        "version": "v2",
        "data_type": "metrics",
        "name": name,
        "unit": unit,
        "source": source_name(point.get("source")),
        "start": point.get("start") or point.get("startDate") or point.get("date"),
        "end": point.get("end") or point.get("endDate"),
        "value": point.get("qty"),
    }
    if point.get("qty") is None:
        identity["complex_value"] = point
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "hae:v2:metric:" + hashlib.sha256(encoded).hexdigest()


def metrics_from_health_auto_export_v2(record: dict[str, Any]) -> list[MetricValue]:
    metrics_payload = record.get("data", {}).get("metrics") if isinstance(record.get("data"), dict) else None
    if not isinstance(metrics_payload, list):
        return []

    metrics: list[MetricValue] = []
    for metric_group in metrics_payload:
        if not isinstance(metric_group, dict):
            continue
        name = metric_group.get("name")
        unit = metric_group.get("units")
        points = metric_group.get("data")
        if not name or not isinstance(points, list):
            continue
        for point in points:
            if not isinstance(point, dict):
                continue
            record = {
                "metric_name": name,
                "unit": unit,
                "point": point,
                "health_auto_export": {"version": "v2", "data_type": "metrics"},
            }
            metrics.extend(metrics_from_health_auto_export_v2_point_record(record))
    return metrics


def source_name(source: Any) -> str:
    if isinstance(source, str) and source:
        return source
    if isinstance(source, dict):
        for key in ("name", "sourceName", "bundleIdentifier", "id"):
            value = source.get(key)
            if value:
                return str(value)
    return "apple_health"
