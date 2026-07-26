"""SQLAlchemy engine, session factory, and base."""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import get_settings

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


def init_db() -> None:
    from backend import models  # noqa: F401  ensure domain models are registered
    from backend.dataset import models as dataset_models  # noqa: F401  dataset tables

    Base.metadata.create_all(bind=engine)
