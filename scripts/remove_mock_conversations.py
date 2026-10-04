"""Find (and with --apply, delete) conversations that are the offline mock LLM's
canned template, plus the dataset entries linked to them.

These were saved while the app ran with LLM_PROVIDER=mock: every one carries
the marker "(offline templated response)" (or its Kannada form). They are not
real answers, so they should not sit in chat history or the training dataset.

    python scripts/remove_mock_conversations.py            # list only
    python scripts/remove_mock_conversations.py --apply    # back up, then delete
"""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root on path

from sqlalchemy import func, or_, select  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402
from backend.dataset.models import DatasetEntry  # noqa: E402
from backend.models import Conversation  # noqa: E402

MARKERS = ("offline templated response", "ಆಫ್‌ಲೈನ್ ಟೆಂಪ್ಲೇಟ್ ಉತ್ತರ")


def main() -> int:
    apply = "--apply" in sys.argv
    url = get_settings().database_url
    init_db()
    with SessionLocal() as db:
        mock = or_(*[Conversation.answer.contains(m) for m in MARKERS])
        convs = list(db.execute(select(Conversation).where(mock).order_by(Conversation.id)).scalars())
        ids = [c.id for c in convs]
        entries = list(db.execute(
            select(DatasetEntry).where(DatasetEntry.conversation_reference.in_(ids))
        ).scalars()) if ids else []
        print(f"conversations total: {db.scalar(select(func.count(Conversation.id)))}, "
              f"mock-template: {len(convs)}")
        for c in convs:
            print(f"  #{c.id} {c.timestamp:%Y-%m-%d %H:%M} [{c.language}] Q: {c.question[:50]!r} "
                  f"A: {c.answer[:60]!r}...")
        print(f"dataset entries total: {db.scalar(select(func.count(DatasetEntry.id)))}, "
              f"linked to them: {len(entries)}")
        for e in entries:
            print(f"  entry #{e.id} obs {e.observation_id} conversation #{e.conversation_reference} "
                  f"labels={e.labels} quality={e.quality_score}")
        if not apply:
            print("\n(list only; run with --apply to back up the database and delete these)")
            return 0
        if url.startswith("sqlite"):
            path = Path(url.split("///")[-1]).resolve()
            backup = path.with_name(path.name + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(path, backup)
            print(f"\nbacked up -> {backup.name}")
        for e in entries:
            db.delete(e)
        for c in convs:
            db.delete(c)
        db.commit()
        print(f"deleted {len(convs)} conversations and {len(entries)} dataset entries")
        print(f"after: conversations {db.scalar(select(func.count(Conversation.id)))}, "
              f"mock-template {db.scalar(select(func.count(Conversation.id)).where(mock))}, "
              f"dataset entries {db.scalar(select(func.count(DatasetEntry.id)))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
