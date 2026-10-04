"""One-time migration: hash node API keys that are still stored in plaintext.

Backs the SQLite file up first, then runs the same idempotent function the
server runs at startup (services.node_keys.hash_plaintext_keys). Devices keep
using the key they already have; nothing changes on the ESP32.

    python scripts/hash_node_keys.py

Run with the same NODE_KEY_SECRET / JWT_SECRET the server uses, or devices
will be rejected (the stored hash depends on that secret).
"""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root on path

from sqlalchemy import select  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.core.security import is_hashed_node_key  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402
from backend.models import Node  # noqa: E402
from backend.services.node_keys import hash_plaintext_keys  # noqa: E402


def main() -> int:
    url = get_settings().database_url
    if url.startswith("sqlite"):
        path = Path(url.split("///")[-1]).resolve()
        if path.exists():
            backup = path.with_name(path.name + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(path, backup)
            print(f"backed up -> {backup.name}")
    init_db()
    with SessionLocal() as db:
        nodes = list(db.execute(select(Node)).scalars())
        print(f"nodes: {len(nodes)}, plaintext keys before: "
              f"{sum(not is_hashed_node_key(n.api_key) for n in nodes)}")
        changed = hash_plaintext_keys(db)
        db.commit()
        print(f"hashed now: {changed}")
        print(f"plaintext keys after: "
              f"{sum(not is_hashed_node_key(n.api_key) for n in db.execute(select(Node)).scalars())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
