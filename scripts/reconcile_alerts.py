"""Close alerts that newer sensor readings already show are over.

Runs the same code path the server runs at startup (services.alerts.
reconcile_open_alerts), so a database can be healed without starting the app.
Backs the SQLite file up first. Stop any running server before using it.

    python scripts/reconcile_alerts.py
"""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root on path

from sqlalchemy import select  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402
from backend.models import Alert  # noqa: E402
from backend.services import alerts  # noqa: E402


def main() -> int:
    url = get_settings().database_url
    if url.startswith("sqlite"):
        path = Path(url.split("///")[-1]).resolve()
        if path.exists():
            backup = path.with_name(path.name + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(path, backup)
            print(f"backed up -> {backup.name}")

    init_db()  # adds any new columns (e.g. resolved_at, resolution) the normal way
    with SessionLocal() as db:
        before = list(db.execute(select(Alert).where(Alert.resolved.is_(False))).scalars())
        print(f"open alerts before: {len(before)}")
        for a in before:
            print(f"  #{a.id} {a.type} '{a.message}' raised {a.created_at:%Y-%m-%d}")
        closed = alerts.reconcile_open_alerts(db)
        db.commit()
        print(f"resolved: {len(closed)}")
        for a in closed:
            print(f"  #{a.id} {a.type} -> {a.resolution}")
        still = db.execute(select(Alert).where(Alert.resolved.is_(False))).scalars().all()
        print(f"open alerts after: {len(still)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
