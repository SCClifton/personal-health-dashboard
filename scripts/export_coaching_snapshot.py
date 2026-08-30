from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from health_dashboard.db import SessionLocal, init_db
from health_dashboard.services.coaching import build_coaching_snapshot
from health_dashboard.services.ingestion import daily_feature_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a local, read-only coaching snapshot for Claude, Cursor, and Codex.")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--out", default=str(ROOT / "local_exports" / "coaching"))
    args = parser.parse_args()

    init_db()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    with SessionLocal() as db:
        rows = daily_feature_rows(db, days=args.days)
        snapshot = build_coaching_snapshot(db, rows, days=args.days)
        payload = {
            "generated_at": generated_at,
            "agent_instructions": agent_instructions(),
            "generated_for_days": snapshot.generated_for_days,
            "goal": snapshot.goal,
            "adherence": snapshot.adherence,
            "training_sleep": snapshot.training_sleep,
            "source_freshness": snapshot.source_freshness,
            "missing_data_actions": snapshot.missing_data_actions,
        }

    json_path = out_dir / f"coaching_snapshot_{generated_at}.json"
    md_path = out_dir / f"coaching_snapshot_{generated_at}.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


def agent_instructions() -> list[str]:
    return [
        "Use this as read-only local context; do not infer missing health facts.",
        "Do not provide medical, dosing, or treatment recommendations.",
        "Keep coaching suggestions focused on adherence, data completeness, sleep hygiene, training consistency, and questions to discuss with a clinician.",
        "Do not request or expose secrets, raw provider payloads, tokens, or credential files.",
    ]


def render_markdown(payload: dict) -> str:
    goal = payload["goal"].get("goal") or {}
    lines = [
        "# Personal Health Coaching Snapshot",
        "",
        f"Generated: {payload['generated_at']}",
        f"Window: {payload['generated_for_days']} days",
        "",
        "## Agent Instructions",
        *[f"- {item}" for item in payload["agent_instructions"]],
        "",
        "## Goal",
        f"- Start: {goal.get('start_weight_kg', '-')} kg on {goal.get('start_date', '-')}",
        f"- Target: {goal.get('target_weight_kg', '-')} kg by {goal.get('target_date', '-')}",
        f"- Actual loss: {fmt(payload['goal'].get('actual_loss_kg'))} kg",
        f"- Expected loss so far: {fmt(payload['goal'].get('expected_loss_kg'))} kg",
        f"- Remaining loss: {fmt(payload['goal'].get('remaining_loss_kg'))} kg",
        "",
        "## Nutrition Adherence",
        f"- Calories logged: {payload['adherence']['calories_logged_days']}/28 days",
        f"- Protein logged: {payload['adherence']['protein_logged_days']}/28 days",
        f"- Average calories: {fmt(payload['adherence'].get('average_calories'))}",
        f"- Average protein: {fmt(payload['adherence'].get('average_protein_g'))} g",
        "",
        "## Missing Data Actions",
        *[f"- {item}" for item in payload["missing_data_actions"]],
        "",
        "## Source Freshness",
    ]
    for item in payload["source_freshness"]:
        lines.append(f"- {item['provider']}: raw={item['last_raw_event_at'] or '-'}, observed={item['last_observed_at'] or '-'}")
    lines.append("")
    return "\n".join(lines)


def fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


if __name__ == "__main__":
    main()
