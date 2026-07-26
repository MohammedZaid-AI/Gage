"""SQLAlchemy engine, session factory, and base."""
import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import get_settings

logger = logging.getLogger("gage.db")

settings = get_settings()

# check_same_thread=False so the same SQLite connection can serve FastAPI's threads.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _sync_missing_columns() -> None:
    """Non-destructive self-heal for dev DBs that predate a column addition.

    `create_all` adds missing *tables* but never adds *columns* to existing ones, so
    an old dev DB drifts and 500s (e.g. "no such column: farms.crop_type"). This adds
    any model column missing from an existing table via ALTER ADD COLUMN. It never
    drops or alters existing columns. ponytail: a stopgap until Alembic; add real
    migrations before there is production data to preserve.
    """
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue  # create_all handles brand-new tables
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            coltype = col.type.compile(engine.dialect)
            default = ""
            # only inline a simple scalar default (e.g. crop_type='sugarcane'); a
            # NOT NULL constraint is intentionally omitted since SQLite cannot add one.
            if col.default is not None and getattr(col.default, "is_scalar", False):
                arg = col.default.arg
                default = f" DEFAULT {arg!r}" if isinstance(arg, str) else f" DEFAULT {arg}"
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}{default}'))
            logger.warning("schema self-heal: added missing column %s.%s", table.name, col.name)


def init_db() -> None:
    from backend import models  # noqa: F401  ensure domain models are registered
    from backend.dataset import models as dataset_models  # noqa: F401  dataset tables

    Base.metadata.create_all(bind=engine)
    _sync_missing_columns()
