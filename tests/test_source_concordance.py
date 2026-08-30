from health_dashboard.services.ingestion import store_raw_event
from health_dashboard.services.source_concordance import build_source_concordance_report, render_source_concordance_markdown, source_family


def _store_metric(db_session, *, provider: str, source: str, metric_name: str, value: float, observed_start: str, observed_end: str | None = None) -> None:
    payload = {
        "id": f"{provider}:{source}:{metric_name}:{observed_start}",
        "metric_name": metric_name,
        "value": value,
        "unit": "h" if metric_name == "sleep_duration" else "ms",
        "observed_start": observed_start,
        "observed_end": observed_end,
        "source": source,
    }
    store_raw_event(db_session, provider=provider, payload=payload)


def test_hrv_concordance_reports_same_day_source_delta(db_session) -> None:
    _store_metric(
        db_session,
        provider="whoop",
        source="whoop",
        metric_name="hrv",
        value=40,
        observed_start="2026-06-20T07:00:00+10:00",
    )
    _store_metric(
        db_session,
        provider="oura",
        source="oura",
        metric_name="hrv",
        value=37,
        observed_start="2026-06-20T06:00:00+10:00",
    )
    db_session.commit()

    report = build_source_concordance_report(db_session, days=3650, tz_name="Australia/Sydney")

    assert report["hrv"][0]["date"] == "2026-06-20"
    assert report["hrv"][0]["max_delta_ms"] == 3
    assert report["hrv"][0]["sources"] == {"Oura": 37.0, "WHOOP": 40.0}


def test_sleep_concordance_flags_eight_sleep_bed_level_discordance(db_session) -> None:
    _store_metric(
        db_session,
        provider="whoop",
        source="whoop",
        metric_name="sleep_duration",
        value=8,
        observed_start="2026-06-19T22:00:00+10:00",
        observed_end="2026-06-20T06:00:00+10:00",
    )
    _store_metric(
        db_session,
        provider="oura",
        source="oura",
        metric_name="sleep_duration",
        value=7.8,
        observed_start="2026-06-19T22:12:00+10:00",
        observed_end="2026-06-20T06:00:00+10:00",
    )
    _store_metric(
        db_session,
        provider="apple_health",
        source="Eight Sleep",
        metric_name="sleep_duration",
        value=10.5,
        observed_start="2026-06-19T19:30:00+10:00",
        observed_end="2026-06-20T06:00:00+10:00",
    )
    db_session.commit()

    report = build_source_concordance_report(db_session, days=3650, tz_name="Australia/Sydney")
    markdown = render_source_concordance_markdown(report)

    flags = report["sleep"]["bed_sharing_flags"]
    assert flags
    assert flags[0]["wake_date"] == "2026-06-20"
    assert "Eight Sleep start differs" in flags[0]["reasons"][0]
    assert "Eight Sleep / sleep_duration" in markdown


def test_step_concordance_separates_apple_health_relays_and_prefers_direct_source(db_session) -> None:
    assert source_family("apple_health", "WHOOP|Samuel's Apple Watch|Oura") == "Mixed Apple Health Sources"
    _store_metric(
        db_session,
        provider="apple_health",
        source="WHOOP",
        metric_name="steps",
        value=12_000,
        observed_start="2026-06-20T00:00:00+10:00",
    )
    _store_metric(
        db_session,
        provider="apple_health",
        source="Apple Watch",
        metric_name="steps",
        value=8_000,
        observed_start="2026-06-20T00:00:00+10:00",
    )
    _store_metric(
        db_session,
        provider="apple_health",
        source="Oura",
        metric_name="steps",
        value=9_900,
        observed_start="2026-06-20T00:00:00+10:00",
    )
    _store_metric(
        db_session,
        provider="oura",
        source="oura",
        metric_name="steps",
        value=10_000,
        observed_start="2026-06-20T00:00:00+10:00",
    )
    db_session.commit()

    report = build_source_concordance_report(db_session, days=3650, tz_name="Australia/Sydney")
    comparison = report["daily_comparisons"]["steps"]
    entry = comparison["comparisons"][0]

    assert entry["sources"] == {"Apple Watch": 8000.0, "Oura": 10000.0, "WHOOP": 12000.0}
    assert entry["routes"] == {
        "Apple Watch": "apple_health_relay",
        "Oura": "direct_api",
        "WHOOP": "apple_health_relay",
    }
    assert {item["source"] for item in report["metric_coverage"] if item["metric"] == "steps"} == {
        "Apple Watch",
        "Oura",
        "WHOOP",
    }
    assert "Oura vs WHOOP" in render_source_concordance_markdown(report)
