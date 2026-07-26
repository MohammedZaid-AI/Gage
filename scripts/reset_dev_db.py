"""Reset the local dev SQLite database to the current schema.

Backs up the existing DB (never deletes) then recreates the tables and re-seeds
the demo data. Use this after a schema change while the project has no Alembic
migrations — `create_all` adds missing tables but never adds columns to existing
ones, so an old dev DB drifts and 500s (e.g. "no such column: farms.crop_type").

NOT for production. Stop any running server first (the DB file must not be locked).

    python scripts/reset_dev_db.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root on path

from backend.config import get_settings  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402
from backend.seed import seed_demo  # noqa: E402


def main() -> int:
    url = get_settings().database_url
    if not url.startswith("sqlite"):
        print(f"Refusing: {url!r} is not a SQLite DB — use a real migration tool.")
        return 1
    path = Path(url.split("///")[-1]).resolve()

    if path.exists():
        backup = path.with_name(path.name + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            os.rename(path, backup)  # atomic: fails cleanly (no copy) if the file is locked
        except (PermissionError, OSError):
            print(f"Cannot move {path.name}: it is in use. Stop the running server first.")
            return 1
        print(f"backed up old DB  -> {backup.name}")

    init_db()
    with SessionLocal() as db:
        seed_demo(db)
    print(f"fresh DB created + seeded -> {path}")
    print("Restart the server to pick up the new schema.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
