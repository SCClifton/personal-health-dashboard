from __future__ import annotations

import html
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from health_dashboard.connectors.base import ConnectorInfo
from health_dashboard.models import DailyFeature, DoseChangeContext
from health_dashboard.services.analytics import (
    ChangeWindow,
    RelationshipReadout,
    calculate_bmi,
    change_window,
    metric_snapshot,
    paired_relationship,
    trend_points,
    value_for_metric,
)
from health_dashboard.services.coaching import AdherenceSummary, GoalProgress
from health_dashboard.services.relationships import (
    Baseline,
    CorrelationResult,
    Coverage,
    baselines,
    coverage,
    metric_label,
    readiness_note,
    recovery_flags,
)
from health_dashboard.services.run_analysis import RunListItem, RunRecoveryAnalysis, RunRepeatRecovery
from health_dashboard.services.sync_queue import SyncQueueSnapshot

try:
    import plotly.graph_objects as go
    from plotly.io import to_html
except Exception:  # pragma: no cover - exercised only when optional dependency is unavailable
    go = None
    to_html = None


@dataclass(frozen=True)
class SourceHealthRow:
    name: str
    status: str
    detail: str
    next_action: str
    last_sync_at: str
    last_raw_event_at: str
    last_normalized_metric_at: str
    action: str | None = None


NAV = """
<nav>
  <a href="/">Overview</a>
  <a href="/dashboard/coach">Coach</a>
  <a href="/dashboard/cardiometabolic">Cardiometabolic</a>
  <a href="/dashboard/glp1">GLP-1</a>
  <a href="/dashboard/sleep">Recovery & Sleep</a>
  <a href="/dashboard/training">Training Load</a>
  <a href="/dashboard/runs">Runs</a>
  <a href="/dashboard/correlation-lab">Relationship Lab</a>
  <a href="/dashboard/data-quality">Data Quality</a>
</nav>
"""


STYLE = """
<style>
:root {
  --bg: #f4f6f5;
  --surface: #ffffff;
  --ink: #17211d;
  --muted: #65746d;
  --line: #d8e1dc;
  --line-soft: #e9eeeb;
  --green: #157f5b;
  --green-bg: #dcf2e8;
  --teal: #0f8a8a;
  --amber: #b87900;
  --amber-bg: #fff3cd;
  --red: #a33a38;
  --red-bg: #f9dddd;
  --blue: #2867a8;
  --blue-bg: #e3eefb;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: var(--bg); }
header { padding: 22px 32px 12px; background: var(--surface); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 5; }
h1 { margin: 0 0 5px; font-size: 26px; letter-spacing: 0; }
h2 { margin: 0 0 10px; font-size: 18px; letter-spacing: 0; }
h3 { margin: 0 0 8px; font-size: 15px; letter-spacing: 0; }
nav { display: flex; flex-wrap: wrap; gap: 7px; padding-top: 10px; }
nav a { color: #195640; text-decoration: none; padding: 7px 10px; border-radius: 6px; background: #edf5f0; font-size: 14px; }
main { padding: 22px 32px 42px; }
.page-kicker { color: var(--muted); font-size: 14px; max-width: 980px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
.metric-grid { display: grid; grid-template-columns: repeat(7, minmax(150px, 1fr)); gap: 10px; }
.two-col { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, .44fr); gap: 14px; align-items: start; }
.chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 14px; }
.card, .panel, .chart-card { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }
.card { min-height: 124px; }
.metric-name { color: var(--muted); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
.metric { font-size: 25px; font-weight: 700; margin: 8px 0 6px; line-height: 1.05; }
.metric-sub { display: grid; grid-template-columns: 1fr 1fr; gap: 5px 8px; color: var(--muted); font-size: 12px; }
.muted { color: var(--muted); font-size: 13px; }
.section { margin-top: 22px; }
.tight { margin-top: 12px; }
.status, .badge, .readiness { display: inline-flex; align-items: center; gap: 4px; padding: 3px 7px; border-radius: 999px; font-size: 12px; line-height: 1.2; background: #eef1ef; color: #33413b; white-space: nowrap; }
.connected, .configured, .ok, .usable { background: var(--green-bg); color: #15543d; }
.missing_credentials, .watch, .early_signal { background: var(--amber-bg); color: #765500; }
.approval_gated, .fallback_only, .info { background: var(--blue-bg); color: #224872; }
.error, .data_insufficient { background: var(--red-bg); color: #7c2020; }
.warning { padding: 12px; border: 1px solid #e5c46f; background: #fff8df; border-radius: 8px; margin-bottom: 14px; }
.notice { padding: 12px; border: 1px solid #bed2ea; background: #eef6ff; border-radius: 8px; margin-bottom: 14px; }
.flag-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.flag { border-radius: 8px; padding: 9px 10px; font-size: 13px; border: 1px solid transparent; }
.flag.ok { border-color: #b9e5cd; }
.flag.watch { border-color: #ead187; }
.source-list { display: grid; gap: 5px; min-width: 220px; }
.source-line { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.source-metric { color: var(--muted); font-size: 12px; min-width: 92px; }
.context-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; }
.context-item { border: 1px solid var(--line-soft); border-radius: 8px; padding: 10px; background: #fbfcfb; }
.note-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; margin-top: 10px; }
table { width: 100%; border-collapse: separate; border-spacing: 0; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
th, td { padding: 9px 11px; border-bottom: 1px solid var(--line-soft); text-align: left; vertical-align: top; font-size: 13px; }
th { background: #edf5ef; font-size: 12px; color: #34423c; position: sticky; top: 78px; z-index: 1; }
tr:last-child td { border-bottom: 0; }
.compact td, .compact th { padding: 8px 9px; }
.button { border: 1px solid #b8c8c0; background: #fff; border-radius: 6px; padding: 6px 9px; color: #173f31; font: inherit; font-size: 13px; cursor: pointer; }
.button:hover { background: #f0f6f3; }
.controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; }
.controls label { display: grid; gap: 4px; font-size: 12px; color: var(--muted); }
select, input { min-height: 34px; border: 1px solid #bdcac4; border-radius: 6px; background: #fff; color: var(--ink); padding: 5px 8px; font: inherit; }
textarea { min-height: 64px; border: 1px solid #bdcac4; border-radius: 6px; background: #fff; color: var(--ink); padding: 7px 8px; font: inherit; resize: vertical; }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.form-grid label { display: grid; gap: 4px; font-size: 12px; color: var(--muted); }
.chart-card { min-height: 360px; }
.plotly-graph-div { width: 100% !important; }
@media (max-width: 1100px) {
  .metric-grid { grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); }
  .two-col { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  header, main { padding-left: 16px; padding-right: 16px; }
  .chart-grid { grid-template-columns: 1fr; }
  .metric-sub { grid-template-columns: 1fr; }
  th { top: 116px; }
}
</style>
"""


def shell(title: str, body: str, subtitle: str | None = None) -> str:
    kicker = f"<div class='page-kicker'>{html.escape(subtitle)}</div>" if subtitle else ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"{STYLE}<title>{html.escape(title)}</title></head><body>"
        f"<header><h1>{html.escape(title)}</h1>{kicker}{NAV}</header><main>{body}</main></body></html>"
    )


def render_dashboard(title: str, rows: list[DailyFeature], metrics: list[str], height_cm: float | None = None) -> str:
    cards = "".join(render_metric_card(metric_snapshot(rows, metric, height_cm), height_cm=height_cm) for metric in metrics)
    table = render_daily_table(rows[-14:], metrics)
    return shell(title, f"<div class='metric-grid'>{cards}</div><section class='section'><h2>Recent Daily Features</h2>{table}</section>")


def render_glp1_dashboard(rows: list[DailyFeature], dose_context: DoseChangeContext | None, height_cm: float | None = None) -> str:
    metrics = [
        "tirzepatide_dose_mg",
        "weight",
        "bmi",
        "calories",
        "protein",
        "systolic_bp",
        "diastolic_bp",
        "resting_hr",
        "hrv",
        "sleep_duration",
        "training_load",
        "workout_count",
    ]
    cards = "".join(render_metric_card(metric_snapshot(rows, metric, height_cm), height_cm=height_cm) for metric in metrics)
    event_date = dose_context.planned_start_date if dose_context else None
    charts = [
        render_line_chart("Weight", rows, "weight", "kg", include_js=True, event_date=event_date),
        render_line_chart("Blood pressure systolic", rows, "systolic_bp", "mmHg", include_js=False, event_date=event_date),
        render_line_chart("Resting heart rate", rows, "resting_hr", "bpm", include_js=False, event_date=event_date),
        render_line_chart("HRV", rows, "hrv", "ms", include_js=False, event_date=event_date),
        render_line_chart("Protein", rows, "protein", "g", include_js=False, event_date=event_date),
        render_line_chart("Training load", rows, "training_load", "load", include_js=False, event_date=event_date),
    ]
    window_rows = dose_context_window(rows, event_date)
    window_heading = "Dose-Change Monitoring Window" if event_date else "Recent GLP-1 Data"
    return shell(
        "GLP-1 Response",
        "<div class='warning'>This page tracks source-backed medication context and biomarkers only. It is not medical advice and does not recommend dosing or treatment changes.</div>"
        + render_dose_context_panel(dose_context)
        + f"<section class='metric-grid'>{cards}</section>"
        + f"<section class='section chart-grid'>{''.join(charts)}</section>"
        + f"<section class='section'><h2>{html.escape(window_heading)}</h2>"
        + render_daily_table(window_rows, metrics)
        + "</section>",
        "Tirzepatide dose history, planned dose-change context, and source-aware weight, nutrition, BP, recovery, sleep, and training markers.",
    )


def render_dose_context_panel(dose_context: DoseChangeContext | None) -> str:
    if dose_context is None:
        return "<div class='notice'>No GLP-1 dose-change context recorded yet. Actual injections can still be logged in the medication dose log.</div>"
    planned = format_metric_value("tirzepatide_dose_mg", dose_context.planned_dose_mg)
    prior = format_metric_value("tirzepatide_dose_mg", dose_context.prior_dose_mg)
    planned_date = dose_context.planned_start_date.isoformat() if dose_context.planned_start_date else "-"
    change_text = f"{prior} to {planned}" if prior != "-" or planned != "-" else "-"
    summary_items = [
        ("Medication", dose_context.medication_name),
        ("Planned change", change_text),
        ("Planned start", planned_date),
        ("Clinician/source", dose_context.clinician_name or "-"),
        ("Source type", dose_context.source_type or "-"),
        ("Source reference", dose_context.source_reference or "-"),
    ]
    summary_html = "".join(
        "<div class='context-item'>"
        f"<div class='metric-name'>{html.escape(label)}</div>"
        f"<div class='muted'>{html.escape(str(value))}</div>"
        "</div>"
        for label, value in summary_items
    )
    notes = [
        ("Preparation Notes", dose_context.preparation_notes),
        ("Monitoring Notes", dose_context.monitoring_notes),
        ("Follow-Up Questions", dose_context.follow_up_questions),
    ]
    notes_html = "".join(
        "<section class='context-item'>"
        f"<h3>{html.escape(label)}</h3>"
        f"<div class='muted'>{html.escape(value or '-')}</div>"
        "</section>"
        for label, value in notes
    )
    return (
        "<section class='section panel'>"
        "<h2>Dose-Change Context</h2>"
        "<div class='muted'>Planned context is kept separate from actual dose administrations.</div>"
        f"<div class='context-list tight'>{summary_html}</div>"
        f"<div class='note-grid'>{notes_html}</div>"
        "</section>"
    )


def dose_context_window(rows: list[DailyFeature], planned_start_date: date | None) -> list[DailyFeature]:
    if planned_start_date is None:
        return rows[-45:]
    start = planned_start_date - timedelta(days=14)
    end = planned_start_date + timedelta(days=42)
    window = [row for row in rows if start <= row.date <= end]
    return window or rows[-14:]


def render_overview(rows: list[DailyFeature], height_cm: float | None = None) -> str:
    cards = [
        render_metric_card(metric_snapshot(rows, "weight", height_cm)),
        render_metric_card(metric_snapshot(rows, "bmi", height_cm), height_cm=height_cm),
        render_bp_card(rows),
        render_metric_card(metric_snapshot(rows, "hrv", height_cm)),
        render_metric_card(metric_snapshot(rows, "resting_hr", height_cm)),
        render_metric_card(metric_snapshot(rows, "sleep_duration", height_cm)),
        render_metric_card(metric_snapshot(rows, "training_load", height_cm)),
    ]
    warnings = []
    if height_cm is None:
        warnings.append("Height is not configured, so BMI is hidden rather than estimated. Set HEIGHT_CM locally to enable BMI.")
    bp_count = sum(1 for row in rows if row.systolic_bp is not None or row.diastolic_bp is not None)
    if bp_count == 0:
        warnings.append("No blood pressure readings are normalized yet. Hilo readings should appear after Apple Health posts BP data.")
    warning_html = "".join(f"<div class='warning'>{html.escape(item)}</div>" for item in warnings)
    trends = []
    trends.append(render_line_chart("Weight trend", rows, "weight", "kg", include_js=True))
    trends.append(render_line_chart("Recovery trend", rows, "hrv", "ms", include_js=False))
    trends.append(render_line_chart("Training load trend", rows, "training_load", "load", include_js=False))
    return shell(
        "Overview",
        warning_html
        + f"<div class='metric-grid'>{''.join(cards)}</div>"
        + f"<section class='section chart-grid'>{''.join(trends)}</section>"
        + "<section class='section'><h2>Detailed Daily Features</h2>"
        + render_daily_table(rows[-21:], ["weight", "systolic_bp", "diastolic_bp", "resting_hr", "hrv", "sleep_duration", "training_load", "calories", "protein", "tirzepatide_dose_mg"])
        + "</section>",
        "Latest values, 7-day and 28-day averages, source labels, and freshness for local cardiometabolic, recovery, sleep, and training data.",
    )


def render_coaching_dashboard(
    rows: list[DailyFeature],
    progress: GoalProgress,
    adherence: AdherenceSummary,
    actions: list[str],
) -> str:
    goal = progress.goal
    warning_html = (
        "<div class='warning'>This dashboard is for tracking and coaching context only. It is not medical advice and does not make medication, dosing, or treatment recommendations.</div>"
    )
    goal_form = render_goal_form(progress)
    target_text = "-"
    if goal:
        target_text = f"{goal.start_weight_kg:.1f} kg to {goal.target_weight_kg:.1f} kg by {goal.target_date.isoformat()}"
    cards = [
        coaching_card("Goal", target_text, f"Target pace {format_metric_value('weight', progress.target_weekly_loss_kg)} per week" if progress.target_weekly_loss_kg is not None else "Set a goal to enable pace tracking."),
        coaching_card("Latest weight", format_metric_value("weight", progress.latest_weight_kg), f"Fresh through {progress.latest_weight_date.isoformat()}" if progress.latest_weight_date else "No weigh-in yet."),
        coaching_card("Actual loss", format_signed(progress.actual_loss_kg), f"Expected {format_metric_value('weight', progress.expected_loss_kg)} so far" if progress.expected_loss_kg is not None else "No expected-loss line yet."),
        coaching_card("Remaining", format_metric_value("weight", progress.remaining_loss_kg), f"{progress.remaining_days} days left" if progress.remaining_days is not None else "No target date set."),
        coaching_card("Calories logged", f"{adherence.calories_logged_days}/28", target_hit_text(adherence.calorie_target_days, adherence.calories_logged_days, "days at or below target")),
        coaching_card("Protein logged", f"{adherence.protein_logged_days}/28", target_hit_text(adherence.protein_target_days, adherence.protein_logged_days, "days at or above target")),
        coaching_card("Training", format_metric_value("training_load", metric_snapshot(rows, "training_load").average_7d), "7-day average training load"),
        coaching_card("Sleep", format_metric_value("sleep_duration", metric_snapshot(rows, "sleep_duration").average_7d), "7-day average sleep duration"),
    ]
    action_items = "".join(f"<li>{html.escape(item)}</li>" for item in actions) or "<li>No high-priority missing-data actions for this window.</li>"
    charts = [
        render_line_chart("Weight trend against goal context", rows, "weight", "kg", include_js=True),
        render_line_chart("Calories", rows, "calories", "kcal", include_js=False),
        render_line_chart("Protein", rows, "protein", "g", include_js=False),
        render_line_chart("Training load", rows, "training_load", "load", include_js=False),
        render_line_chart("Sleep duration", rows, "sleep_duration", "hours", include_js=False),
    ]
    return shell(
        "Coach",
        warning_html
        + f"<section class='metric-grid'>{''.join(cards)}</section>"
        + f"<section class='section panel'><h2>Missing Data Actions</h2><ul>{action_items}</ul></section>"
        + goal_form
        + f"<section class='section chart-grid'>{''.join(charts)}</section>"
        + "<section class='section'><h2>Recent Coaching Data</h2>"
        + render_daily_table(rows[-45:], ["weight", "calories", "protein", "training_load", "workout_count", "sleep_duration", "hrv", "resting_hr"])
        + "</section>",
        "Weight-loss progress, nutrition adherence, training context, sleep context, and source-aware gaps for agent coaching snapshots.",
    )


def coaching_card(label: str, value: str, detail: str) -> str:
    return (
        "<section class='card'>"
        f"<div class='metric-name'>{html.escape(label)}</div>"
        f"<div class='metric'>{html.escape(value)}</div>"
        f"<div class='muted'>{html.escape(detail)}</div>"
        "</section>"
    )


def target_hit_text(hit_days: int, logged_days: int, label: str) -> str:
    if logged_days == 0:
        return "No logged days in the last 28 days."
    return f"{hit_days}/{logged_days} {label}."


def render_goal_form(progress: GoalProgress) -> str:
    goal = progress.goal
    start_date = goal.start_date.isoformat() if goal else ""
    target_date = goal.target_date.isoformat() if goal else ""
    start_weight = "" if goal is None else f"{goal.start_weight_kg:.1f}"
    target_weight = "" if goal is None else f"{goal.target_weight_kg:.1f}"
    calories = "" if goal is None or goal.daily_calorie_target is None else f"{goal.daily_calorie_target:.0f}"
    protein = "" if goal is None or goal.daily_protein_target_g is None else f"{goal.daily_protein_target_g:.0f}"
    notes = "" if goal is None or goal.notes is None else goal.notes
    return (
        "<section class='section panel'><h2>Goal Settings</h2>"
        "<form method='post' action='/coach/goal'>"
        "<div class='form-grid'>"
        f"<label>Start date<input type='date' name='start_date' value='{html.escape(start_date)}' required></label>"
        f"<label>Target date<input type='date' name='target_date' value='{html.escape(target_date)}' required></label>"
        f"<label>Start weight kg<input type='number' step='0.1' name='start_weight_kg' value='{html.escape(start_weight)}' required></label>"
        f"<label>Target weight kg<input type='number' step='0.1' name='target_weight_kg' value='{html.escape(target_weight)}' required></label>"
        f"<label>Daily calories<input type='number' step='1' name='daily_calorie_target' value='{html.escape(calories)}'></label>"
        f"<label>Daily protein g<input type='number' step='1' name='daily_protein_target_g' value='{html.escape(protein)}'></label>"
        "</div>"
        f"<label class='tight' style='display:grid;gap:4px;font-size:12px;color:var(--muted)'>Notes<textarea name='notes'>{html.escape(notes)}</textarea></label>"
        "<div class='tight'><button class='button' type='submit'>Save goal</button></div>"
        "</form></section>"
    )


def render_cardiometabolic(rows: list[DailyFeature], height_cm: float | None = None) -> str:
    warnings = []
    if height_cm is None:
        warnings.append("Height is not configured. BMI cards and BMI charts are intentionally withheld until HEIGHT_CM is set.")
    bp_count = sum(1 for row in rows if row.systolic_bp is not None and row.diastolic_bp is not None)
    if bp_count < 3:
        warnings.append("Blood pressure data is insufficient. Hilo/Apple Health BP can populate this once readings land.")
    warning_html = "".join(f"<div class='warning'>{html.escape(item)}</div>" for item in warnings)
    insight_cards = [
        render_change_card(change_window(rows, "weight", days, height_cm)) for days in (30, 90, 180)
    ]
    if height_cm is not None:
        insight_cards.extend(render_change_card(change_window(rows, "bmi", days, height_cm)) for days in (30, 90, 180))
    insight_cards.extend(render_bp_change_card(rows, days) for days in (30, 90, 180))
    charts = [
        render_weight_bmi_chart(rows, height_cm, include_js=True),
        render_bp_chart(rows, include_js=False),
        render_scatter_chart("Weight vs systolic BP", rows, "weight", "systolic_bp", "kg", "mmHg", height_cm, include_js=False),
        render_scatter_chart("Weight vs diastolic BP", rows, "weight", "diastolic_bp", "kg", "mmHg", height_cm, include_js=False),
    ]
    if height_cm is not None:
        charts.extend(
            [
                render_scatter_chart("BMI vs systolic BP", rows, "bmi", "systolic_bp", "BMI", "mmHg", height_cm, include_js=False),
                render_scatter_chart("BMI vs diastolic BP", rows, "bmi", "diastolic_bp", "BMI", "mmHg", height_cm, include_js=False),
            ]
        )
    charts.append(render_weekly_bp_chart(rows, include_js=False))
    return shell(
        "Cardiometabolic Progress",
        warning_html
        + "<div class='notice'>Weight and BMI move together by definition when height is fixed: as weight comes down, BMI should come down too. BP relationships shown here are exploratory and source-aware.</div>"
        + f"<section class='grid'>{''.join(insight_cards)}</section>"
        + f"<section class='section chart-grid'>{''.join(charts)}</section>"
        + "<section class='section'><h2>Recent Cardiometabolic Data</h2>"
        + render_daily_table(rows[-45:], ["weight", "systolic_bp", "diastolic_bp", "calories", "protein"])
        + "</section>",
        "Core 3-6 month view for weight, BMI, blood pressure, and early cardiometabolic response signals.",
    )


def render_recovery_sleep(rows: list[DailyFeature]) -> str:
    charts = [
        render_line_chart("HRV with 7-day baseline", rows, "hrv", "ms", include_js=True),
        render_line_chart("Resting HR with 7-day baseline", rows, "resting_hr", "bpm", include_js=False),
        render_line_chart("Sleep duration with 7-day baseline", rows, "sleep_duration", "hours", include_js=False),
        render_line_chart("Sleep efficiency", rows, "sleep_efficiency", "%", include_js=False),
        render_baseline_deviation_chart(rows, ["hrv", "resting_hr", "sleep_duration", "training_load"], include_js=False),
    ]
    bedtime_support = any((row.source_flags or {}).get("sleep_duration") for row in rows)
    consistency = (
        "<div class='notice'>Sleep duration sources are present. Bedtime consistency can be added once normalized bedtime/wake-time fields are available.</div>"
        if bedtime_support
        else "<div class='warning'>Sleep consistency needs sleep start/end data in normalized daily features. No supported bedtime series is available yet.</div>"
    )
    return shell(
        "Recovery & Sleep",
        render_baseline_panel(rows, ["hrv", "resting_hr", "sleep_duration", "sleep_efficiency", "training_load"])
        + consistency
        + f"<section class='section chart-grid'>{''.join(charts)}</section>"
        + "<section class='section'><h2>Recent Recovery Data</h2>"
        + render_daily_table(rows[-45:], ["hrv", "resting_hr", "sleep_duration", "sleep_efficiency", "training_load"])
        + "</section>",
        "Plain-English recovery context from rolling baselines. These flags are exploratory, not diagnostic.",
    )


def render_training_load(rows: list[DailyFeature], lag_days: int = 1) -> str:
    relationship = paired_relationship(rows, "training_load", "hrv", lag_days=lag_days, days=180)
    charts = [
        render_line_chart("Training load", rows, "training_load", "load", include_js=True),
        render_line_chart("Workout count", rows, "workout_count", "count", include_js=False),
        render_source_split_chart(rows, include_js=False),
        render_line_chart("Active energy", rows, "active_energy", "kcal", include_js=False),
        render_relationship_scatter("Training load vs next HRV", relationship, "Training load", "HRV", include_js=False),
        render_dual_axis_chart(rows, "training_load", "resting_hr", lag_days=lag_days, include_js=False),
    ]
    controls = render_lag_controls("/dashboard/training", lag_days)
    return shell(
        "Training Load",
        controls
        + render_relationship_summary(relationship)
        + f"<section class='section chart-grid'>{''.join(charts)}</section>"
        + "<section class='section'><h2>Recent Training Data</h2>"
        + render_daily_table(rows[-45:], ["training_load", "workout_count", "active_energy", "hrv", "resting_hr", "sleep_duration"])
        + "</section>",
        "Training stress, source coverage, active energy, and lagged next-day recovery relationships.",
    )


def render_runs_dashboard(runs: list[RunListItem], analysis: RunRecoveryAnalysis | None, *, days: int) -> str:
    sync_panel = (
        "<section class='panel'><h2>Run Detail Sync</h2>"
        "<div class='muted'>Summary Strava sync stays lightweight. Use rich run sync only when you need laps and heart-rate streams for interval analysis.</div>"
        f"<form class='controls tight' method='post' action='/sync/strava/runs?days={days}'>"
        "<button class='button' type='submit'>Sync recent run detail</button>"
        "</form></section>"
    )
    if not runs:
        return shell(
            "Run Recovery",
            sync_panel
            + "<div class='warning'>No recent Strava runs are stored locally for this window. Sync Strava run detail after the activity appears in Strava.</div>"
            + render_recent_runs_table(runs),
            "Repeat-level heart-rate recovery from Strava run laps and streams. Garmin remains approval-gated; local FIT import is the fallback path.",
        )

    warning_html = ""
    if analysis:
        warning_html = "".join(f"<div class='warning'>{html.escape(item)}</div>" for item in analysis.warnings)
        if not warning_html:
            warning_html = "<div class='notice'>Latest run has enough lap and heart-rate stream data for repeat-level recovery analysis.</div>"
    body = (
        sync_panel
        + warning_html
        + (render_run_recovery_summary(analysis) if analysis else "")
        + "<section class='section'><h2>Detected 400 m Repeats</h2>"
        + (render_run_recovery_table(analysis.repeats) if analysis else "<div class='muted'>No run selected.</div>")
        + "</section>"
        + "<section class='section'><h2>Recent Strava Runs</h2>"
        + render_recent_runs_table(runs)
        + "</section>"
    )
    return shell(
        "Run Recovery",
        body,
        "Repeat-level heart-rate recovery from Strava run laps and streams. Garmin remains approval-gated; local FIT import is the fallback path.",
    )


def render_run_recovery_summary(analysis: RunRecoveryAnalysis) -> str:
    statuses = "".join(
        f"<span class='badge {'ok' if present else 'watch'}'>{html.escape(label)}</span>"
        for label, present in (
            ("summary", analysis.source_status.get("summary", False)),
            ("detail", analysis.source_status.get("detail", False)),
            ("laps", analysis.source_status.get("laps", False)),
            ("streams", analysis.source_status.get("streams", False)),
            ("HR", analysis.source_status.get("heartrate", False)),
        )
    )
    cards = [
        ("Run", analysis.name),
        ("Start", format_datetime(analysis.start_date)),
        ("Distance", format_distance_m(analysis.distance_m)),
        ("Elapsed", format_duration_s(analysis.elapsed_time_s)),
        ("Repeats", str(analysis.repeat_count)),
        ("Confidence", analysis.confidence.replace("_", " ")),
    ]
    card_html = "".join(
        "<section class='card'>"
        f"<div class='metric-name'>{html.escape(label)}</div>"
        f"<div class='metric'>{html.escape(value)}</div>"
        "</section>"
        for label, value in cards
    )
    return (
        "<section class='section panel'>"
        "<h2>Latest Run Analysis</h2>"
        f"<div class='flag-row'>{statuses}</div>"
        f"<div class='grid tight'>{card_html}</div>"
        "</section>"
    )


def render_run_recovery_table(repeats: list[RunRepeatRecovery]) -> str:
    if not repeats:
        return "<div class='muted'>No 350-450 m repeat laps detected yet.</div>"
    rows = []
    for item in repeats:
        rows.append(
            "<tr>"
            f"<td>{item.rep_number}</td>"
            f"<td>{html.escape(format_distance_m(item.distance_m))}</td>"
            f"<td>{html.escape(format_duration_s(item.duration_s))}</td>"
            f"<td>{html.escape(format_pace(item.pace_sec_per_km))}</td>"
            f"<td>{html.escape(format_hr(item.peak_hr_bpm))}</td>"
            f"<td>{html.escape(format_hr(item.hr_at_rest_start_bpm))}</td>"
            f"<td>{html.escape(format_hr_drop(item.hr_drop_60s_bpm))}</td>"
            f"<td>{html.escape(format_hr_drop(item.hr_drop_120s_bpm))}</td>"
            f"<td>{html.escape(format_hr(item.min_rest_hr_bpm))}</td>"
            f"<td>{html.escape(format_hr(item.hr_at_next_rep_start_bpm))}</td>"
            "</tr>"
        )
    return (
        "<table class='compact'><tr><th>Rep</th><th>Distance</th><th>Duration</th><th>Pace</th><th>Peak HR</th>"
        "<th>Rest start HR</th><th>60s drop</th><th>120s drop</th><th>Min rest HR</th><th>Next rep HR</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def render_recent_runs_table(runs: list[RunListItem]) -> str:
    rows = []
    for item in runs:
        status = "".join(
            f"<span class='badge {'ok' if present else 'watch'}'>{html.escape(label)}</span>"
            for label, present in (
                ("detail", item.has_detail),
                ("laps", item.has_laps),
                ("streams", item.has_streams),
                ("HR", item.has_heartrate),
            )
        )
        rows.append(
            "<tr>"
            f"<td>{html.escape(format_datetime(item.start_date))}</td>"
            f"<td>{html.escape(item.name)}</td>"
            f"<td>{html.escape(format_distance_m(item.distance_m))}</td>"
            f"<td>{html.escape(format_duration_s(item.elapsed_time_s))}</td>"
            f"<td><div class='flag-row'>{status}</div></td>"
            f"<td><form method='post' action='/sync/strava/runs?activity_id={html.escape(item.activity_id)}'><button class='button' type='submit'>Sync detail</button></form></td>"
            "</tr>"
        )
    empty = '<tr><td colspan="6">No recent runs stored locally.</td></tr>'
    return "<table class='compact'><tr><th>Start</th><th>Name</th><th>Distance</th><th>Elapsed</th><th>Local detail</th><th></th></tr>" + ("".join(rows) or empty) + "</table>"


def render_correlation_lab(
    rows: list[DailyFeature],
    *,
    height_cm: float | None = None,
    metric_a: str = "training_load",
    metric_b: str = "hrv",
    lag_days: int = 1,
    days: int = 180,
) -> str:
    metric_a = metric_a if metric_a in relationship_metrics(height_cm) else "training_load"
    metric_b = metric_b if metric_b in relationship_metrics(height_cm) else "hrv"
    relationship = paired_relationship(rows, metric_a, metric_b, lag_days=lag_days, days=days, height_cm=height_cm)
    body = (
        "<div class='warning'>Relationships here are exploratory and are not diagnostic. Treat them as prompts for better questions, not as medical, dosing, or treatment guidance. Lag +1 compares Metric A with the following day's Metric B.</div>"
        + render_relationship_controls(metric_a, metric_b, lag_days, days, height_cm)
        + render_relationship_summary(relationship)
        + "<section class='section chart-grid'>"
        + render_relationship_scatter("Scatter with regression line", relationship, metric_label(metric_a), metric_label(metric_b), include_js=True)
        + render_relationship_dual_axis_from_pairs(relationship, include_js=False)
        + "</section>"
        + render_coverage_table(coverage(rows, relationship_metrics(height_cm)))
        + "<section class='section'><h2>Recent Daily Features</h2>"
        + render_daily_table(rows[-30:], ["weight", "calories", "protein", "systolic_bp", "diastolic_bp", "sleep_duration", "hrv", "resting_hr", "training_load", "workout_count"])
        + "</section>"
    )
    return shell("Relationship Lab", body, "Metric controls, lag selection, date range, sample-size gating, missingness, and source-aware caveats.")


def render_connector_status(infos: list[ConnectorInfo]) -> str:
    rows = []
    for info in infos:
        docs = f"<a href='{html.escape(info.official_docs_url)}'>docs</a>" if info.official_docs_url else ""
        rows.append(
            "<tr>"
            f"<td>{html.escape(info.name)}</td>"
            f"<td><span class='status {html.escape(info.status.value)}'>{html.escape(info.status.value)}</span></td>"
            f"<td>{html.escape(info.detail)}</td>"
            f"<td>{html.escape(info.next_action)} {docs}</td>"
            f"<td>{html.escape(info.last_sync_at.isoformat() if info.last_sync_at else '')}</td>"
            f"<td>{html.escape(info.last_error or '')}</td>"
            "</tr>"
        )
    body = "<table><tr><th>Connector</th><th>Status</th><th>Detail</th><th>Next Action</th><th>Last Sync</th><th>Last Error</th></tr>" + "".join(rows) + "</table>"
    return shell("Connector Status", body)


def render_data_quality(
    source_rows: list[SourceHealthRow],
    warnings: list[str],
    queue: SyncQueueSnapshot,
) -> str:
    warning_html = "".join(f"<div class='warning'>{html.escape(item)}</div>" for item in warnings) or "<div class='notice'>No high-priority missing-data warnings for the current window.</div>"
    queue_text = "Idle"
    if queue.current_provider:
        queue_text = f"Running {queue.current_provider}"
    queue_html = (
        "<section class='panel'><h2>Sync Lock</h2>"
        f"<div class='metric'>{html.escape(queue_text)}</div>"
        f"<div class='muted'>Queued syncs: {queue.queued_count}. Provider syncs pass through this local process lock before writing SQLite.</div>"
        "</section>"
    )
    rows = []
    for item in source_rows:
        action = ""
        if item.action:
            action = f"<form method='post' action='{html.escape(item.action)}'><button class='button' type='submit'>Sync now</button></form>"
        rows.append(
            "<tr>"
            f"<td>{html.escape(item.name)}</td>"
            f"<td><span class='status {html.escape(item.status)}'>{html.escape(item.status)}</span></td>"
            f"<td>{html.escape(item.last_raw_event_at)}</td>"
            f"<td>{html.escape(item.last_normalized_metric_at)}</td>"
            f"<td>{html.escape(item.last_sync_at)}</td>"
            f"<td>{html.escape(item.next_action)}</td>"
            f"<td>{action}</td>"
            "</tr>"
        )
    table = (
        "<table><tr><th>Source</th><th>Status</th><th>Last raw event</th><th>Last normalized metric</th><th>Last sync</th><th>Next action</th><th></th></tr>"
        + "".join(rows)
        + "</table>"
    )
    return shell(
        "Data Quality",
        warning_html + queue_html + f"<section class='section'><h2>Sources</h2>{table}</section>",
        "Connector health, freshness, missing-data warnings, and local sync coordination.",
    )


def render_daily_table(rows: Iterable[DailyFeature], metrics: list[str]) -> str:
    header = "<tr><th>Date</th>" + "".join(f"<th>{html.escape(metric_label(metric))}</th>" for metric in metrics) + "<th>Sources</th></tr>"
    body = []
    for row in rows:
        cells = "".join(f"<td>{format_metric_value(metric, value_for_metric(row, metric))}</td>" for metric in metrics)
        body.append(f"<tr><td>{row.date.isoformat()}</td>{cells}<td>{render_source_flags(row.source_flags or {}, metrics)}</td></tr>")
    empty = '<tr><td colspan="20">No data imported yet.</td></tr>'
    return f"<table>{header}{''.join(body) or empty}</table>"


def render_metric_card(snapshot, height_cm: float | None = None) -> str:
    if snapshot.metric == "bmi" and height_cm is None:
        metric = "<span class='muted'>Height required</span>"
    else:
        metric = format_metric_value(snapshot.metric, snapshot.latest)
    freshness = "No data" if snapshot.latest_date is None else f"Fresh through {snapshot.latest_date.isoformat()}"
    source = friendly_source(snapshot.source or "")
    source_badge = f"<span class='badge'>{html.escape(source)}</span>" if source else "<span class='badge info'>No source</span>"
    return (
        "<section class='card'>"
        f"<div class='metric-name'>{html.escape(metric_label(snapshot.metric))}</div>"
        f"<div class='metric'>{metric}</div>"
        "<div class='metric-sub'>"
        f"<span>7d {format_metric_value(snapshot.metric, snapshot.average_7d)}</span>"
        f"<span>28d {format_metric_value(snapshot.metric, snapshot.average_28d)}</span>"
        f"<span>Delta {format_signed(snapshot.delta_28d)}</span>"
        f"<span>{source_badge}</span>"
        "</div>"
        f"<div class='muted tight'>{html.escape(freshness)}</div>"
        "</section>"
    )


def render_bp_card(rows: list[DailyFeature]) -> str:
    systolic = metric_snapshot(rows, "systolic_bp")
    diastolic = metric_snapshot(rows, "diastolic_bp")
    latest = "-"
    if systolic.latest is not None and diastolic.latest is not None:
        latest = f"{systolic.latest:.0f}/{diastolic.latest:.0f}"
    elif systolic.latest is not None:
        latest = f"{systolic.latest:.0f}/-"
    elif diastolic.latest is not None:
        latest = f"-/{diastolic.latest:.0f}"
    source = friendly_source(systolic.source or diastolic.source or "")
    source_badge = f"<span class='badge'>{html.escape(source)}</span>" if source else "<span class='badge info'>No source</span>"
    date_text = systolic.latest_date or diastolic.latest_date
    freshness = "No BP data" if date_text is None else f"Fresh through {date_text.isoformat()}"
    return (
        "<section class='card'>"
        "<div class='metric-name'>Blood Pressure</div>"
        f"<div class='metric'>{html.escape(latest)}</div>"
        "<div class='metric-sub'>"
        f"<span>7d {format_bp_pair(systolic.average_7d, diastolic.average_7d)}</span>"
        f"<span>28d {format_bp_pair(systolic.average_28d, diastolic.average_28d)}</span>"
        f"<span>Delta {format_bp_pair(systolic.delta_28d, diastolic.delta_28d, signed=True)}</span>"
        f"<span>{source_badge}</span>"
        "</div>"
        f"<div class='muted tight'>{html.escape(freshness)}</div>"
        "</section>"
    )


def render_change_card(item: ChangeWindow) -> str:
    if item.change is None:
        detail = "Data insufficient"
        value = "-"
        badge = "<span class='readiness data_insufficient'>insufficient</span>"
    else:
        detail = f"{format_metric_value(item.metric, item.previous)} to {format_metric_value(item.metric, item.latest)}"
        value = format_signed(item.change)
        badge = "<span class='readiness usable'>trend</span>"
    return (
        "<section class='card'>"
        f"<div class='metric-name'>{html.escape(metric_label(item.metric))} {item.days}d</div>"
        f"<div class='metric'>{html.escape(value)}</div>"
        f"<div class='muted'>{html.escape(detail)}</div>"
        f"<div class='tight'>{badge}</div>"
        "</section>"
    )


def render_bp_change_card(rows: list[DailyFeature], days: int) -> str:
    sys_change = change_window(rows, "systolic_bp", days)
    dia_change = change_window(rows, "diastolic_bp", days)
    enough = sys_change.change is not None and dia_change.change is not None and min(sys_change.sample_count, dia_change.sample_count) >= 3
    value = format_bp_pair(sys_change.change, dia_change.change, signed=True) if enough else "-"
    detail = "Data insufficient until more BP readings land" if not enough else "Systolic/diastolic change"
    badge = "usable" if enough else "data_insufficient"
    return (
        "<section class='card'>"
        f"<div class='metric-name'>BP {days}d</div>"
        f"<div class='metric'>{html.escape(value)}</div>"
        f"<div class='muted'>{html.escape(detail)}</div>"
        f"<div class='tight'><span class='readiness {badge}'>{html.escape(badge.replace('_', ' '))}</span></div>"
        "</section>"
    )


def render_baseline_panel(rows: list[DailyFeature], metrics: list[str]) -> str:
    flags = recovery_flags(rows)
    baseline_rows = baselines(rows, metrics)
    cards = "".join(render_baseline_card(item) for item in baseline_rows)
    flag_html = "".join(f"<div class='flag {html.escape(flag.level)}'><strong>{html.escape(flag.label)}</strong><br>{html.escape(flag.detail)}</div>" for flag in flags)
    return (
        "<section class='section panel'>"
        "<h2>Rolling Baselines</h2>"
        "<div class='muted'>7-day trailing baselines make recovery, sleep, and training changes easier to scan.</div>"
        f"<div class='grid tight'>{cards}</div>"
        "<h2 class='section'>Recovery Flags</h2>"
        "<div class='muted'>Simple exploratory flags from HRV, resting HR, sleep, and training load.</div>"
        f"<div class='flag-row'>{flag_html}</div>"
        "</section>"
    )


def render_baseline_card(item: Baseline) -> str:
    return (
        "<section class='card'>"
        f"<div class='metric-name'>{html.escape(metric_label(item.metric))}</div>"
        f"<div class='metric'>{format_metric_value(item.metric, item.latest)}</div>"
        f"<div class='muted'>7-day {format_metric_value(item.metric, item.trailing_7d)} · delta {format_signed(item.delta)}</div>"
        "</section>"
    )


def render_relationship_summary(result: RelationshipReadout) -> str:
    r_text = "-" if result.r is None or result.n < 14 else f"{result.r:.2f}"
    if result.readiness == "data_insufficient":
        caveat = "Minimum sample size not met. No relationship conclusion is shown for n < 14."
    elif result.readiness == "early_signal":
        caveat = "Early signal only. Direction and size may move materially as data fills in."
    else:
        caveat = "Usable for exploration, still not causal or diagnostic."
    return (
        "<section class='panel tight'>"
        "<h2>Readout</h2>"
        "<div class='grid'>"
        f"<div><div class='metric-name'>Pearson r</div><div class='metric'>{html.escape(r_text)}</div></div>"
        f"<div><div class='metric-name'>Sample size</div><div class='metric'>{result.n}</div></div>"
        f"<div><div class='metric-name'>Missingness</div><div class='metric'>{result.missingness_pct:.0f}%</div></div>"
        f"<div><div class='metric-name'>Readiness</div><div class='metric'><span class='readiness {html.escape(result.readiness)}'>{html.escape(result.readiness.replace('_', ' '))}</span></div></div>"
        "</div>"
        f"<div class='muted'>{html.escape(caveat)}</div>"
        "</section>"
    )


def render_relationship_controls(metric_a: str, metric_b: str, lag_days: int, days: int, height_cm: float | None) -> str:
    options = relationship_metrics(height_cm)
    metric_a_options = "".join(option(metric, metric_a) for metric in options)
    metric_b_options = "".join(option(metric, metric_b) for metric in options)
    return (
        "<section class='panel'><form class='controls' method='get' action='/dashboard/correlation-lab'>"
        f"<label>Metric A<select name='metric_a'>{metric_a_options}</select></label>"
        f"<label>Metric B<select name='metric_b'>{metric_b_options}</select></label>"
        f"<label>Lag<select name='lag'>{option_value('0', '0 days', lag_days == 0)}{option_value('1', '+1 day', lag_days == 1)}{option_value('2', '+2 days', lag_days == 2)}{option_value('7', '+7 days', lag_days == 7)}</select></label>"
        f"<label>Date range<select name='days'>{option_value('30', '30 days', days == 30)}{option_value('90', '90 days', days == 90)}{option_value('180', '180 days', days == 180)}{option_value('365', '365 days', days == 365)}</select></label>"
        "<button class='button' type='submit'>Update</button>"
        "</form></section>"
    )


def render_lag_controls(action: str, lag_days: int) -> str:
    return (
        f"<section class='panel'><form class='controls' method='get' action='{html.escape(action)}'>"
        f"<label>Lag selector<select name='lag'>{option_value('0', '0 days', lag_days == 0)}{option_value('1', '+1 day', lag_days == 1)}{option_value('2', '+2 days', lag_days == 2)}{option_value('7', '+7 days', lag_days == 7)}</select></label>"
        "<button class='button' type='submit'>Update</button></form></section>"
    )


def render_coverage_table(items: list[Coverage]) -> str:
    rows = []
    for item in items:
        rows.append(
            "<tr>"
            f"<td>{html.escape(metric_label(item.metric))}</td>"
            f"<td>{item.count}/{item.total}</td>"
            f"<td>{item.pct:.0f}%</td>"
            f"<td>{html.escape(item.first_date.isoformat() if item.first_date else '-')}</td>"
            f"<td>{html.escape(item.last_date.isoformat() if item.last_date else '-')}</td>"
            f"<td>{format_metric_value(item.metric, item.latest_value)}</td>"
            f"<td>{html.escape(readiness_note(item))}</td>"
            "</tr>"
        )
    return (
        "<section class='section'>"
        "<h2>Data Readiness</h2>"
        "<table class='compact'><tr><th>Metric</th><th>Coverage</th><th>%</th><th>First</th><th>Last</th><th>Latest</th><th>Use</th></tr>"
        + "".join(rows)
        + "</table></section>"
    )


def render_line_chart(
    title: str,
    rows: list[DailyFeature],
    metric: str,
    y_title: str,
    *,
    include_js: bool,
    height_cm: float | None = None,
    bands: list[tuple[float, float, str, str]] | None = None,
    event_date: date | None = None,
) -> str:
    points = trend_points(rows, metric, height_cm)
    if not any(point.value is not None for point in points):
        return empty_chart(title, "No data for this metric yet.")
    if go is None or to_html is None:
        return empty_chart(title, "Plotly is not installed.")
    fig = go.Figure()
    x = [point.date.isoformat() for point in points]
    fig.add_trace(go.Scatter(x=x, y=[point.value for point in points], mode="markers", name="raw dots", marker={"size": 6, "color": "#2867a8"}))
    fig.add_trace(go.Scatter(x=x, y=[point.average_7d for point in points], mode="lines", name="7-day", line={"color": "#0f8a8a", "width": 2}))
    fig.add_trace(go.Scatter(x=x, y=[point.average_28d for point in points], mode="lines", name="28-day", line={"color": "#17211d", "width": 2}))
    apply_bands(fig, x, bands)
    apply_event_marker(fig, x, event_date, "planned dose change")
    return chart_card(title, fig, include_js, y_title)


def render_weight_bmi_chart(rows: list[DailyFeature], height_cm: float | None, *, include_js: bool) -> str:
    if height_cm is None:
        return render_line_chart("Weight trend", rows, "weight", "kg", include_js=include_js)
    if go is None or to_html is None:
        return empty_chart("Weight and BMI", "Plotly is not installed.")
    weight = trend_points(rows, "weight")
    bmi = trend_points(rows, "bmi", height_cm)
    x = [point.date.isoformat() for point in weight]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=[point.value for point in weight], mode="markers", name="weight raw", marker={"size": 6, "color": "#2867a8"}, yaxis="y"))
    fig.add_trace(go.Scatter(x=x, y=[point.average_7d for point in weight], mode="lines", name="weight 7-day", line={"color": "#0f8a8a", "width": 2}, yaxis="y"))
    fig.add_trace(go.Scatter(x=x, y=[point.average_28d for point in weight], mode="lines", name="weight 28-day", line={"color": "#17211d", "width": 2}, yaxis="y"))
    fig.add_trace(go.Scatter(x=x, y=[point.average_7d for point in bmi], mode="lines", name="BMI 7-day", line={"color": "#b87900", "width": 2}, yaxis="y2"))
    fig.update_layout(yaxis2={"title": "BMI", "overlaying": "y", "side": "right", "showgrid": False})
    return chart_card("Weight and BMI over time", fig, include_js, "kg")


def render_bp_chart(rows: list[DailyFeature], *, include_js: bool) -> str:
    if go is None or to_html is None:
        return empty_chart("Blood pressure", "Plotly is not installed.")
    sys = trend_points(rows, "systolic_bp")
    dia = trend_points(rows, "diastolic_bp")
    if not any(point.value is not None for point in sys + dia):
        return empty_chart("Blood pressure", "No BP readings yet. Hilo via Apple Health can populate this.")
    x = [point.date.isoformat() for point in sys]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=[point.value for point in sys], mode="markers", name="systolic raw", marker={"size": 6, "color": "#2867a8"}))
    fig.add_trace(go.Scatter(x=x, y=[point.average_7d for point in sys], mode="lines", name="systolic 7-day", line={"color": "#0f8a8a", "width": 2}))
    fig.add_trace(go.Scatter(x=x, y=[point.value for point in dia], mode="markers", name="diastolic raw", marker={"size": 6, "color": "#6f5aa8"}))
    fig.add_trace(go.Scatter(x=x, y=[point.average_7d for point in dia], mode="lines", name="diastolic 7-day", line={"color": "#b87900", "width": 2}))
    apply_bands(fig, x, bp_bands())
    return chart_card("Systolic and diastolic BP", fig, include_js, "mmHg")


def render_scatter_chart(title: str, rows: list[DailyFeature], metric_a: str, metric_b: str, x_title: str, y_title: str, height_cm: float | None, *, include_js: bool) -> str:
    relationship = paired_relationship(rows, metric_a, metric_b, lag_days=0, days=365, height_cm=height_cm)
    return render_relationship_scatter(title, relationship, x_title, y_title, include_js=include_js)


def render_weekly_bp_chart(rows: list[DailyFeature], *, include_js: bool) -> str:
    readings = [(row.date, row.systolic_bp, row.diastolic_bp) for row in rows if row.systolic_bp is not None and row.diastolic_bp is not None]
    if not readings:
        return empty_chart("Weekly BP average", "Data insufficient until BP readings land.")
    if go is None or to_html is None:
        return empty_chart("Weekly BP average", "Plotly is not installed.")
    buckets: dict[str, list[tuple[float, float]]] = {}
    for day, sys, dia in readings:
        monday = day.fromordinal(day.toordinal() - day.weekday())
        buckets.setdefault(monday.isoformat(), []).append((float(sys), float(dia)))
    x = sorted(buckets)
    sys_y = [sum(item[0] for item in buckets[key]) / len(buckets[key]) for key in x]
    dia_y = [sum(item[1] for item in buckets[key]) / len(buckets[key]) for key in x]
    counts = [len(buckets[key]) for key in x]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=counts, name="reading count", marker={"color": "#d9e3de"}, yaxis="y2"))
    fig.add_trace(go.Scatter(x=x, y=sys_y, mode="lines+markers", name="weekly systolic", line={"color": "#2867a8", "width": 2}))
    fig.add_trace(go.Scatter(x=x, y=dia_y, mode="lines+markers", name="weekly diastolic", line={"color": "#b87900", "width": 2}))
    fig.update_layout(yaxis2={"title": "readings", "overlaying": "y", "side": "right", "showgrid": False})
    return chart_card("Weekly BP average with reading count", fig, include_js, "mmHg")


def render_baseline_deviation_chart(rows: list[DailyFeature], metrics: list[str], *, include_js: bool) -> str:
    if go is None or to_html is None:
        return empty_chart("Baseline deviation", "Plotly is not installed.")
    fig = go.Figure()
    x = [row.date.isoformat() for row in rows]
    for metric in metrics:
        points = trend_points(rows, metric)
        y = []
        for point in points:
            if point.value is None or point.average_7d in (None, 0):
                y.append(None)
            else:
                y.append((point.value - point.average_7d) / point.average_7d * 100)
        if any(value is not None for value in y):
            fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=metric_label(metric)))
    return chart_card("Percent from 7-day baseline", fig, include_js, "%")


def render_source_split_chart(rows: list[DailyFeature], *, include_js: bool) -> str:
    if go is None or to_html is None:
        return empty_chart("Source split", "Plotly is not installed.")
    x = [row.date.isoformat() for row in rows]
    series = {"strava": [], "whoop": [], "apple_health": []}
    for row in rows:
        sources = " ".join(str(source).lower() for source in (row.source_flags or {}).get("training_load", []))
        for source in series:
            series[source].append(row.training_load if source in sources else None)
    if not any(any(value is not None for value in values) for values in series.values()):
        return empty_chart("Strava vs WHOOP source split", "No training-load source flags yet.")
    fig = go.Figure()
    colors = {"strava": "#fc4c02", "whoop": "#17211d", "apple_health": "#2867a8"}
    labels = {"strava": "Strava", "whoop": "WHOOP", "apple_health": "Apple Health"}
    for source, values in series.items():
        fig.add_trace(go.Scatter(x=x, y=values, mode="markers", name=labels[source], marker={"size": 7, "color": colors[source]}))
    return chart_card("Strava vs WHOOP training-load source flags", fig, include_js, "load")


def render_relationship_scatter(title: str, relationship: RelationshipReadout, x_title: str, y_title: str, *, include_js: bool) -> str:
    if not relationship.pairs:
        return empty_chart(title, "No overlapping samples yet.")
    if go is None or to_html is None:
        return empty_chart(title, "Plotly is not installed.")
    xs = [pair[1] for pair in relationship.pairs]
    ys = [pair[2] for pair in relationship.pairs]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers", name="samples", marker={"size": 7, "color": "#2867a8"}))
    if relationship.n >= 14:
        line = regression_line(xs, ys)
        if line:
            fig.add_trace(go.Scatter(x=line[0], y=line[1], mode="lines", name="regression", line={"color": "#17211d", "width": 2}))
    fig.update_layout(xaxis_title=x_title, yaxis_title=y_title)
    return chart_card(title, fig, include_js, y_title)


def render_dual_axis_chart(rows: list[DailyFeature], metric_a: str, metric_b: str, *, lag_days: int, include_js: bool) -> str:
    rel = paired_relationship(rows, metric_a, metric_b, lag_days=lag_days, days=180)
    return render_relationship_dual_axis_from_pairs(rel, include_js=include_js)


def render_relationship_dual_axis_from_pairs(relationship: RelationshipReadout, *, include_js: bool) -> str:
    if not relationship.pairs:
        return empty_chart("Time-aligned dual-axis chart", "No overlapping samples yet.")
    if go is None or to_html is None:
        return empty_chart("Time-aligned dual-axis chart", "Plotly is not installed.")
    x = [pair[0].isoformat() for pair in relationship.pairs]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=[pair[1] for pair in relationship.pairs], mode="lines+markers", name=metric_label(relationship.metric_a), line={"color": "#2867a8"}))
    fig.add_trace(go.Scatter(x=x, y=[pair[2] for pair in relationship.pairs], mode="lines+markers", name=metric_label(relationship.metric_b), line={"color": "#b87900"}, yaxis="y2"))
    fig.update_layout(yaxis2={"title": metric_label(relationship.metric_b), "overlaying": "y", "side": "right", "showgrid": False})
    return chart_card("Time-aligned dual-axis chart", fig, include_js, metric_label(relationship.metric_a))


def chart_card(title: str, fig, include_js: bool, y_title: str) -> str:
    fig.update_layout(
        template="plotly_white",
        height=310,
        margin={"l": 45, "r": 30, "t": 16, "b": 38},
        legend={"orientation": "h", "y": -0.18},
        yaxis_title=y_title,
        font={"family": "Inter, system-ui, sans-serif", "size": 12, "color": "#17211d"},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
    )
    config = {"displayModeBar": False, "responsive": True}
    chart = to_html(fig, include_plotlyjs=include_js, full_html=False, config=config)
    return f"<section class='chart-card'><h3>{html.escape(title)}</h3>{chart}</section>"


def empty_chart(title: str, message: str) -> str:
    return f"<section class='chart-card'><h3>{html.escape(title)}</h3><div class='muted'>{html.escape(message)}</div></section>"


def apply_bands(fig, x: list[str], bands: list[tuple[float, float, str, str]] | None) -> None:
    if not bands or not x:
        return
    for low, high, color, label in bands:
        fig.add_shape(type="rect", x0=x[0], x1=x[-1], y0=low, y1=high, fillcolor=color, line_width=0, opacity=0.18, layer="below")
        fig.add_annotation(x=x[-1], y=(low + high) / 2, text=label, showarrow=False, xanchor="right", font={"size": 10, "color": "#33413b"})


def apply_event_marker(fig, x: list[str], event_date: date | None, label: str) -> None:
    if event_date is None or not x:
        return
    event = event_date.isoformat()
    fig.add_shape(
        type="line",
        xref="x",
        yref="paper",
        x0=event,
        x1=event,
        y0=0,
        y1=1,
        line={"width": 1, "dash": "dash", "color": "#a33a38"},
    )
    fig.add_annotation(
        x=event,
        y=1,
        xref="x",
        yref="paper",
        text=label,
        showarrow=False,
        xanchor="left",
        yanchor="bottom",
        font={"size": 10, "color": "#7c2020"},
    )


def bp_bands() -> list[tuple[float, float, str, str]]:
    return [
        (0, 120, "#157f5b", "normal systolic"),
        (120, 130, "#b87900", "elevated"),
        (130, 140, "#d99a20", "stage 1"),
        (140, 180, "#a33a38", "stage 2"),
    ]


def regression_line(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]] | None:
    if len(xs) < 2:
        return None
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denom
    intercept = y_mean - slope * x_mean
    x_line = [min(xs), max(xs)]
    return x_line, [slope * x + intercept for x in x_line]


def render_source_flags(source_flags: dict, metrics: list[str]) -> str:
    lines = []
    for metric in metrics:
        source_key = "weight" if metric == "bmi" else metric
        sources = source_flags.get(source_key)
        if not sources:
            continue
        badges = "".join(f"<span class='badge'>{html.escape(source)}</span>" for source in friendly_sources(sources))
        lines.append(f"<div class='source-line'><span class='source-metric'>{html.escape(metric_label(metric))}</span>{badges}</div>")
    return f"<div class='source-list'>{''.join(lines)}</div>" if lines else "<span class='muted'>-</span>"


def friendly_sources(sources) -> list[str]:
    labels: list[str] = []
    for source in sources:
        for part in str(source).split("|"):
            label = friendly_source(part)
            if label and label not in labels:
                labels.append(label)
    return labels


def friendly_source(source: str) -> str:
    normalized = source.strip().lower()
    if not normalized:
        return ""
    if "strava" in normalized:
        return "Strava"
    if "whoop" in normalized:
        return "WHOOP"
    if "oura" in normalized:
        return "Oura"
    if "eight" in normalized:
        return "Eight Sleep"
    if "myfitnesspal" in normalized:
        return "MyFitnessPal"
    if "hilo" in normalized:
        return "Hilo"
    if "aktiia" in normalized:
        return "Aktiia"
    if "watch" in normalized:
        return "Apple Watch"
    if normalized in {"s clifton", "apple_health", "apple health"}:
        return "Apple Health"
    if normalized == "connect":
        return "Garmin Connect"
    if normalized == "manual_cuff":
        return "Manual cuff"
    return source.strip()


def relationship_metrics(height_cm: float | None) -> list[str]:
    metrics = [
        "weight",
        "calories",
        "protein",
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
    ]
    if height_cm is not None:
        metrics.insert(1, "bmi")
    return metrics


def option(metric: str, selected: str) -> str:
    return option_value(metric, metric_label(metric), metric == selected)


def option_value(value: str, label: str, selected: bool) -> str:
    selected_attr = " selected" if selected else ""
    return f"<option value='{html.escape(value)}'{selected_attr}>{html.escape(label)}</option>"


def format_metric_value(metric: str, value) -> str:
    if value is None:
        return "-"
    if metric in {"systolic_bp", "diastolic_bp", "resting_hr", "workout_count", "steps"}:
        return f"{float(value):.0f}"
    if metric == "bmi":
        return f"{float(value):.1f}"
    if metric == "sleep_efficiency":
        return f"{float(value):.0f}%"
    if metric == "sleep_duration":
        return f"{float(value):.1f}h"
    if metric == "tirzepatide_dose_mg":
        return f"{float(value):.1f} mg"
    if isinstance(value, float):
        return f"{value:.1f}"
    return html.escape(str(value))


def format_value(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.1f}"
    return html.escape(str(value))


def format_datetime(value) -> str:
    if value is None:
        return "-"
    return value.isoformat()


def format_duration_s(value: float | None) -> str:
    if value is None:
        return "-"
    total = int(round(value))
    minutes, seconds = divmod(total, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_distance_m(value: float | None) -> str:
    if value is None:
        return "-"
    if value >= 1000:
        return f"{value / 1000:.2f} km"
    return f"{value:.0f} m"


def format_pace(value: float | None) -> str:
    if value is None:
        return "-"
    minutes, seconds = divmod(int(round(value)), 60)
    return f"{minutes}:{seconds:02d}/km"


def format_hr(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f}"


def format_hr_drop(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.0f}"


def format_signed(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.1f}"


def format_bp_pair(systolic: float | None, diastolic: float | None, *, signed: bool = False) -> str:
    if systolic is None and diastolic is None:
        return "-"
    if signed:
        left = "-" if systolic is None else f"{systolic:+.0f}"
        right = "-" if diastolic is None else f"{diastolic:+.0f}"
    else:
        left = "-" if systolic is None else f"{systolic:.0f}"
        right = "-" if diastolic is None else f"{diastolic:.0f}"
    return f"{left}/{right}"


def relationship_note(result: CorrelationResult) -> str:
    strength = "weak"
    if abs(result.r) >= 0.7:
        strength = "strong"
    elif abs(result.r) >= 0.4:
        strength = "moderate"
    direction = "positive" if result.r > 0 else "negative"
    return html.escape(f"{strength} {direction}; exploratory only")
