from __future__ import annotations

import json
from datetime import date

import httpx

from health_dashboard.connectors.health_auto_export_mcp import (
    HealthAutoExportMcpClient,
    chunk_date_ranges,
    import_mcp_payload,
    payload_item_count,
    tool_arguments,
)
from health_dashboard.models import NormalizedMetric, RawEvent


def test_mcp_client_initializes_and_decodes_tool_text_payload() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        message = json.loads(request.content)
        requests.append(message)
        assert request.headers["authorization"] == "Bearer test-token"
        if message["method"] == "initialize":
            return httpx.Response(
                200,
                headers={"Mcp-Session-Id": "test-session"},
                json={"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": "2025-03-26"}},
            )
        if message["method"] == "notifications/initialized":
            assert request.headers["mcp-session-id"] == "test-session"
            return httpx.Response(202)
        assert request.headers["mcp-session-id"] == "test-session"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {"content": [{"type": "text", "text": '{"data":{"metrics":[]}}'}], "isError": False},
            },
        )

    with HealthAutoExportMcpClient(
        "http://iphone.test/mcp",
        headers_provider=lambda: {"Authorization": "Bearer test-token"},
        transport=httpx.MockTransport(handler),
    ) as client:
        payload = client.call_tool(
            "get_health_metrics",
            {"start": "2026-08-30 00:00:00 +1000", "end": "2026-08-30 23:59:59 +1000"},
        )

    assert payload == {"data": {"metrics": []}}
    assert [request["method"] for request in requests] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]


def test_chunking_and_arguments_preserve_local_day_boundaries_across_dst() -> None:
    chunks = list(chunk_date_ranges(date(2026, 10, 3), date(2026, 10, 6), chunk_days=2))
    assert chunks == [(date(2026, 10, 3), date(2026, 10, 4)), (date(2026, 10, 5), date(2026, 10, 6))]

    before = tool_arguments(
        "get_health_metrics",
        start=date(2026, 10, 3),
        end=date(2026, 10, 3),
        timezone_name="Australia/Sydney",
    )
    after = tool_arguments(
        "get_health_metrics",
        start=date(2026, 10, 4),
        end=date(2026, 10, 4),
        timezone_name="Australia/Sydney",
    )

    assert before["start"].endswith("+1000")
    assert after["end"].endswith("+1100")
    assert before["aggregate"] is True
    assert before["interval"] == "days"


def test_mcp_import_preserves_raw_category_payload_and_normalizes_metrics(db_session) -> None:
    arguments = {
        "start": "2026-08-29 00:00:00 +1000",
        "end": "2026-08-30 23:59:59 +1000",
        "metrics": "",
        "interval": "days",
        "aggregate": True,
    }
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [{"source": "Apple Watch", "qty": 1234, "date": "2026-08-29 00:00:00 +1000"}],
                }
            ]
        }
    }

    first = import_mcp_payload(
        db_session,
        tool_name="get_health_metrics",
        arguments=arguments,
        payload=payload,
        timezone_name="Australia/Sydney",
    )
    db_session.commit()
    second = import_mcp_payload(
        db_session,
        tool_name="get_health_metrics",
        arguments=arguments,
        payload=payload,
        timezone_name="Australia/Sydney",
    )
    db_session.commit()

    envelope = db_session.query(RawEvent).filter(RawEvent.provider == "health_auto_export_mcp").one()
    assert envelope.payload_json["payload"] == payload
    assert envelope.permissions_scope == "get_health_metrics"
    assert first.envelope_imported == 1
    assert first.metric_points_imported == 1
    assert second.envelope_duplicates == 1
    assert second.metric_point_duplicates == 1
    metric = db_session.query(NormalizedMetric).filter(NormalizedMetric.provider == "apple_health").one()
    assert metric.metric_name == "steps"
    assert metric.value_numeric == 1234


def test_non_metric_mcp_category_is_preserved_raw_without_guessing_normalization(db_session) -> None:
    arguments = {"start": "2026-08-29 00:00:00 +1000", "end": "2026-08-30 23:59:59 +1000"}
    payload = {"data": {"electrocardiograms": [{"id": "ecg-1", "classification": "sinusRhythm"}]}}

    result = import_mcp_payload(
        db_session,
        tool_name="get_ecg",
        arguments=arguments,
        payload=payload,
        timezone_name="Australia/Sydney",
    )
    db_session.commit()

    envelope = db_session.query(RawEvent).filter(RawEvent.provider == "health_auto_export_mcp").one()
    assert envelope.payload_json["payload"] == payload
    assert envelope.permissions_scope == "get_ecg"
    assert result.envelope_imported == 1
    assert result.metric_points_imported == 0
    assert db_session.query(NormalizedMetric).count() == 0


def test_payload_item_count_reports_structure_without_reading_values() -> None:
    metrics = {
        "data": {
            "metrics": [
                {"name": "steps", "data": [{"qty": 1}, {"qty": 2}]},
                {"name": "hrv", "data": [{"qty": 3}]},
            ]
        }
    }
    workouts = {"data": {"workouts": [{"id": "one"}, {"id": "two"}]}}

    assert payload_item_count("get_health_metrics", metrics) == 3
    assert payload_item_count("get_workouts", workouts) == 2
