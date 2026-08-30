#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a checked online backup of the local health SQLite database.")
    parser.add_argument("--db", default=str(ROOT / "data" / "health_dashboard.db"), help="SQLite database path.")
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "local_exports" / "db_backups"),
        help="Directory for compressed backup files.",
    )
    parser.add_argument(
        "--check",
        choices=("quick", "full"),
        default="quick",
        help="Run PRAGMA quick_check or integrity_check on the backup before compressing.",
    )
    parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Skip a passive WAL checkpoint after the backup.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    if not db_path.exists():
        raise SystemExit(f"Database does not exist: {db_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = out_dir / f"{db_path.stem}-{timestamp}.sqlite3"
    compressed_path = backup_path.with_suffix(".sqlite3.gz")

    backup_database(db_path, backup_path)
    check_backup(backup_path, full=args.check == "full")
    compress_backup(backup_path, compressed_path)
    if not args.no_checkpoint:
        checkpoint_wal(db_path)

    print(f"Wrote {compressed_path}")


def backup_database(db_path: Path, backup_path: Path) -> None:
    source_uri = f"file:{db_path}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(backup_path) as destination:
        source.backup(destination)


def check_backup(backup_path: Path, *, full: bool) -> None:
    pragma = "integrity_check" if full else "quick_check"
    with sqlite3.connect(backup_path) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        result = db.execute(f"PRAGMA {pragma}").fetchone()
    if result is None or result[0] != "ok":
        raise SystemExit(f"Backup failed {pragma}: {result[0] if result else 'no result'}")


def compress_backup(backup_path: Path, compressed_path: Path) -> None:
    try:
        with backup_path.open("rb") as source, gzip.open(compressed_path, "wb", compresslevel=6) as destination:
            shutil.copyfileobj(source, destination)
    finally:
        backup_path.unlink(missing_ok=True)
        for sidecar in backup_sidecar_paths(backup_path):
            sidecar.unlink(missing_ok=True)


def backup_sidecar_paths(backup_path: Path) -> list[Path]:
    return [
        backup_path.with_name(f"{backup_path.name}-wal"),
        backup_path.with_name(f"{backup_path.name}-shm"),
    ]


def checkpoint_wal(db_path: Path) -> None:
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        db.execute("PRAGMA optimize")


if __name__ == "__main__":
    main()
