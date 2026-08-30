from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from health_dashboard.db import init_db


if __name__ == "__main__":
    init_db()
    print("Database migrations applied idempotently.")
