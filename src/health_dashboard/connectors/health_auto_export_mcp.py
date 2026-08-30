from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from health_dashboard.connectors.apple_health import metrics_from_apple_record, records_from_health_auto_export
from health_dashboard.services.ingestion import payload_hash, rebuild_daily_features, store_raw_event
from health_dashboard.services.time import local_date


MCP_PROTOCOL_VERSION = "2025-03-26"
MCP_TOOL_NAMES = (
    "get_health_metrics",
    "get_workouts",
    "get_heart_notifications",
    "get_ecg",
    "get_symptoms",
    "get_state_of_mind",
    "get_medications",
    "get_cycle_tracking",
)


class HealthAutoExportMcpError(RuntimeError):
    """A safe-to-display MCP failure that never includes response health data."""


@dataclass(frozen=True)
class McpImportResult:
    envelope_imported: int
    envelope_duplicates: int
    metric_points_imported: int
    metric_point_duplicates: int


def headers_from_helper(path: str | Path) -> dict[str, str]:
    helper = Path(path).expanduser()
    try:
        completed = subprocess.run(
            [str(helper)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HealthAutoExportMcpError(f"Could not run MCP headers helper: {helper}") from exc
    if completed.returncode != 0:
        raise HealthAutoExportMcpError(f"MCP headers helper failed: {helper}")
    try:
        headers = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise HealthAutoExportMcpError("MCP headers helper did not return JSON") from exc
    if not isinstance(headers, dict) or not headers:
        raise HealthAutoExportMcpError("MCP headers helper returned no headers")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in headers.items()):
        raise HealthAutoExportMcpError("MCP headers helper returned invalid headers")
    return headers


class HealthAutoExportMcpClient:
    def __init__(
        self,
        endpoint: str,
        *,
        headers_provider: Callable[[], Mapping[str, str]],
        timeout_seconds: float = 120,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.headers_provider = headers_provider
        self.session_id: str | None = None
        self._next_id = 1
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    def __enter__(self) -> HealthAutoExportMcpClient:
        self.initialize()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def initialize(self) -> dict[str, Any]:
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._request_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "personal-health-dashboard", "version": "1"},
                },
            },
            include_session=False,
        )
        self.session_id = response.headers.get("mcp-session-id")
        if not self.session_id:
            raise HealthAutoExportMcpError("MCP server did not return a session ID")
        message = parse_mcp_response(response)
        result = message.get("result")
        if not isinstance(result, dict):
            raise HealthAutoExportMcpError("MCP initialize returned no result")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any] | list[Any]:
        if name not in MCP_TOOL_NAMES:
            raise ValueError(f"Unsupported Health Auto Export MCP tool: {name}")
        if not self.session_id:
            raise HealthAutoExportMcpError("MCP client is not initialized")
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._request_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": dict(arguments)},
            }
        )
        message = parse_mcp_response(response)
        if "error" in message:
            raise HealthAutoExportMcpError(f"MCP tool failed: {name}")
        result = message.get("result")
        if not isinstance(result, dict) or result.get("isError") is True:
            raise HealthAutoExportMcpError(f"MCP tool returned an error: {name}")
        structured = result.get("structuredContent")
        if isinstance(structured, (dict, list)):
            return structured
        for block in result.get("content", []):
            if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
                continue
            try:
                payload = json.loads(block["text"])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, (dict, list)):
                return payload
        raise HealthAutoExportMcpError(f"MCP tool returned no JSON payload: {name}")

    def _request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _post(self, message: Mapping[str, Any], *, include_session: bool = True) -> httpx.Response:
        response = self._post_raw(message, include_session=include_session)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HealthAutoExportMcpError(f"MCP HTTP request failed with status {response.status_code}") from exc
        return response

    def _post_raw(self, message: Mapping[str, Any], *, include_session: bool = True) -> httpx.Response:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            **dict(self.headers_provider()),
        }
        if include_session and self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        try:
            return self._client.post(self.endpoint, headers=headers, json=dict(message))
        except httpx.HTTPError as exc:
            raise HealthAutoExportMcpError(
                "Could not reach the Health Auto Export MCP server. Keep the iPhone unlocked with its Server screen in the foreground."
            ) from exc


def parse_mcp_response(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        candidates = []
        for line in response.text.splitlines():
            if line.startswith("data:"):
                candidates.append(line.removeprefix("data:").strip())
        for candidate in reversed(candidates):
            try:
                message = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                return message
        raise HealthAutoExportMcpError("MCP server returned an unreadable event stream")
    try:
        message = response.json()
    except json.JSONDecodeError as exc:
        raise HealthAutoExportMcpError("MCP server returned unreadable JSON") from exc
    if not isinstance(message, dict):
        raise HealthAutoExportMcpError("MCP server returned an invalid JSON-RPC response")
    return message


def chunk_date_ranges(start: date, end: date, *, chunk_days: int) -> Iterator[tuple[date, date]]:
    if chunk_days < 1:
        raise ValueError("chunk_days must be at least 1")
    if end < start:
        raise ValueError("end must not be before start")
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=chunk_days - 1))
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def tool_arguments(
    name: str,
    *,
    start: date,
    end: date,
    timezone_name: str,
    aggregate_metrics: bool = True,
    include_workout_routes: bool = False,
) -> dict[str, Any]:
    zone = ZoneInfo(timezone_name)
    arguments: dict[str, Any] = {
        "start": datetime.combine(start, time.min, tzinfo=zone).strftime("%Y-%m-%d %H:%M:%S %z"),
        "end": datetime.combine(end, time.max.replace(microsecond=0), tzinfo=zone).strftime("%Y-%m-%d %H:%M:%S %z"),
    }
    if name == "get_health_metrics":
        arguments.update(
            {
                "metrics": "",
                "interval": "days" if aggregate_metrics else "hours",
                "aggregate": aggregate_metrics,
            }
        )
    elif name == "get_workouts":
        arguments.update({"includeMetadata": True, "includeRoutes": include_workout_routes})
    return arguments


def import_mcp_payload(
    db: Session,
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    payload: dict[str, Any] | list[Any],
    timezone_name: str,
    import_batch_id: str | None = None,
) -> McpImportResult:
    batch_id = import_batch_id or str(uuid4())
    envelope = {
        "mcp_tool": tool_name,
        "arguments": dict(arguments),
        "start": arguments.get("start"),
        "end": arguments.get("end"),
        "payload": payload,
    }
    _, envelope_created = store_raw_event(
        db,
        provider="health_auto_export_mcp",
        payload=envelope,
        import_batch_id=batch_id,
        source_record_id=mcp_envelope_id(tool_name=tool_name, arguments=arguments, payload=payload),
        permissions_scope=tool_name,
        schema_version="mcp-1.1.0",
        metrics=[],
    )

    imported = 0
    duplicates = 0
    impacted_dates: list[date] = []
    if tool_name == "get_health_metrics":
        for record in records_from_health_auto_export(payload):
            metrics = metrics_from_apple_record(record)
            _, created = store_raw_event(
                db,
                provider="apple_health",
                payload=record,
                import_batch_id=batch_id,
                permissions_scope="mcp:get_health_metrics",
                schema_version="health-auto-export-v2",
                metrics=metrics,
            )
            imported += int(created)
            duplicates += int(not created)
            if created:
                impacted_dates.extend(local_date(metric.observed_start, timezone_name) for metric in metrics)
    if impacted_dates:
        rebuild_daily_features(db, start=min(impacted_dates), end=max(impacted_dates), tz_name=timezone_name)
    return McpImportResult(
        envelope_imported=int(envelope_created),
        envelope_duplicates=int(not envelope_created),
        metric_points_imported=imported,
        metric_point_duplicates=duplicates,
    )


def mcp_envelope_id(*, tool_name: str, arguments: Mapping[str, Any], payload: dict[str, Any] | list[Any]) -> str:
    identity = {
        "tool": tool_name,
        "arguments": dict(arguments),
        "payload_hash": payload_hash(payload),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "hae:mcp:" + hashlib.sha256(encoded).hexdigest()


def payload_item_count(tool_name: str, payload: dict[str, Any] | list[Any]) -> int:
    """Return a structural record count without exposing health values."""
    if isinstance(payload, list):
        return len(payload)
    data = payload.get("data")
    if not isinstance(data, dict):
        return 1 if payload else 0
    if tool_name == "get_health_metrics":
        groups = data.get("metrics")
        if not isinstance(groups, list):
            return 0
        return sum(
            len(group.get("data", []))
            for group in groups
            if isinstance(group, dict) and isinstance(group.get("data"), list)
        )
    list_values = [value for value in data.values() if isinstance(value, list)]
    if list_values:
        return sum(len(value) for value in list_values)
    return 1 if data else 0
