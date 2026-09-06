#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate or store one local strength-session JSON record.")
    parser.add_argument("input", nargs="?", default="-", help="JSON file path, or - for stdin.")
    parser.add_argument("--commit", action="store_true", help="Write the validated session to the configured local database.")
    parser.add_argument("--database-url", help="Override DATABASE_URL for this process.")
    return parser.parse_args()


def read_payload(path: str) -> dict:
    if path == "-":
        return json.load(sys.stdin)
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    args = parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    from pydantic import ValidationError

    from health_dashboard.api.schemas import StrengthSessionIn
    from health_dashboard.services.strength import import_strength_session, payload_totals, serialize_strength_session

    try:
        session_payload = StrengthSessionIn.model_validate(read_payload(args.input))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    totals = payload_totals(session_payload)
    preview = {
        "validated": True,
        "committed": False,
        "source_record_id": session_payload.source_record_id,
        "started_at": session_payload.started_at.isoformat(),
        "program_name": session_payload.program_name,
        "program_session_name": session_payload.program_session_name,
        "capture_status": session_payload.capture_status,
        "exercise_count": len(session_payload.exercises),
        "totals": totals,
    }
    if not args.commit:
        print(json.dumps(preview, indent=2, sort_keys=True))
        return 0

    from health_dashboard.db import SessionLocal, init_db

    init_db()
    with SessionLocal() as db:
        session, created = import_strength_session(db, session_payload)
        db.commit()
        result = {
            **preview,
            "committed": True,
            "imported": int(created),
            "duplicates": int(not created),
            "session": serialize_strength_session(session),
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
