import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "eight_sleep_whoop_concordance.py"
SPEC = importlib.util.spec_from_file_location("eight_sleep_whoop_concordance", SCRIPT_PATH)
eight_sleep_whoop_concordance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = eight_sleep_whoop_concordance
SPEC.loader.exec_module(eight_sleep_whoop_concordance)


def _write_export(path: Path) -> None:
    payload = {
        "sessions": [
            {
                "ts": 1_781_859_600,  # 2026-06-19 19:00 Australia/Sydney
                "stages": [
                    {"stage": "out", "duration": 1800},
                    {"stage": "awake", "duration": 1800},
                    {"stage": "light", "duration": 18_000},
                    {"stage": "deep", "duration": 9000},
                    {"stage": "rem", "duration": 9000},
                    {"stage": "awake", "duration": 3600},
                ],
                "timeseries": {
                    "heartRate": [["2026-06-19T10:30:00Z", 62], ["2026-06-19T11:30:00Z", 64]],
                    "hrv": [["2026-06-19T10:30:00Z", 51.0], ["2026-06-19T11:30:00Z", 53.0]],
                    "respiratoryRate": [["2026-06-19T10:30:00Z", 14.0], ["2026-06-19T11:30:00Z", 14.4]],
                    "tnt": [["2026-06-19T10:30:00Z", 1]],
                },
            },
            {
                "ts": 1_781_892_000,
                "stages": [{"stage": "light", "duration": 3600}],
                "timeseries": {},
            },
        ]
    }
    with ZipFile(path, "w") as archive:
        archive.writestr("sleep_nights.json", json.dumps(payload))
        archive.writestr("README.md", "Exported Eight Sleep sessions.")
        archive.writestr("user_profile.json", json.dumps({"email": "private@example.com"}))


def _write_whoop_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """
        create table raw_events (
            id text,
            provider text,
            permissions_scope text,
            observed_start text,
            observed_end text,
            payload_json text,
            created_at text
        )
        """
    )
    con.execute(
        """
        create table normalized_metrics (
            provider text,
            source text,
            metric_name text,
            observed_start text
        )
        """
    )
    sleep_payload = {
        "id": "sleep-private-id",
        "cycle_id": "cycle-private-id",
        "start": "2026-06-19T12:00:00+00:00",
        "end": "2026-06-19T21:00:00+00:00",
        "nap": False,
        "score_state": "SCORED",
        "score": {
            "sleep_efficiency_percentage": 88,
            "respiratory_rate": 12.1,
            "stage_summary": {
                "total_light_sleep_time_milli": 14_400_000,
                "total_slow_wave_sleep_time_milli": 7_200_000,
                "total_rem_sleep_time_milli": 7_200_000,
                "total_awake_time_milli": 3_600_000,
                "total_in_bed_time_milli": 32_400_000,
            },
        },
    }
    recovery_payload = {
        "cycle_id": "cycle-private-id",
        "sleep_id": "sleep-private-id",
        "score": {"resting_heart_rate": 55, "hrv_rmssd_milli": 52.0},
    }
    con.execute(
        "insert into raw_events values (?, ?, ?, ?, ?, ?, ?)",
        ("raw-sleep-id", "whoop", "sleep", "2026-06-19 12:00:00.000000", "2026-06-19 21:00:00.000000", json.dumps(sleep_payload), "2026-06-20"),
    )
    con.execute(
        "insert into raw_events values (?, ?, ?, ?, ?, ?, ?)",
        ("raw-recovery-id", "whoop", "recovery", None, None, json.dumps(recovery_payload), "2026-06-20"),
    )
    con.commit()
    con.close()


def test_eight_sleep_parser_tracks_first_sleep_like_and_excludes_short_sessions(tmp_path) -> None:
    export_path = tmp_path / "eight_sleep_data.zip"
    _write_export(export_path)

    sessions, metadata = eight_sleep_whoop_concordance.load_eight_sleep_sessions(export_path)
    selected, audit = eight_sleep_whoop_concordance.select_main_eight_sessions(sessions)

    assert metadata["top_level_session_keys"] == ["stages", "timeseries", "ts"]
    assert len(sessions) == 2
    assert len(selected) == 1
    selected_session = next(iter(selected.values()))
    assert selected_session["first_sleep_like"] > selected_session["first_non_out"]
    assert any("short_lt_3h" in row["audit_flags"] for row in audit)


def test_build_artifacts_flags_bed_occupancy_without_leaking_raw_ids(tmp_path) -> None:
    export_path = tmp_path / "eight_sleep_data.zip"
    db_path = tmp_path / "health_dashboard.db"
    out_dir = tmp_path / "out"
    _write_export(export_path)
    _write_whoop_db(db_path)

    paths = eight_sleep_whoop_concordance.build_artifacts(export_path, db_path, out_dir, analysis_date="2026-06-20")

    summary = json.loads(paths.summary_json.read_text(encoding="utf-8"))
    report = paths.report.read_text(encoding="utf-8")
    overlap = paths.overlap_csv.read_text(encoding="utf-8")

    assert summary["comparison_summary"]["all_overlap"]["n"] == 1
    assert summary["comparison_summary"]["all_overlap"]["eight_starts_90_min_earlier"] == 1
    assert "strong bed-occupancy signal" in overlap
    assert "Eight Sleep" in report
    assert "H-Sleep" not in report
    assert "private@example.com" not in report
    assert "sleep-private-id" not in report
    assert "cycle-private-id" not in report
