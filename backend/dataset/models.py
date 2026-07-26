"""Dataset Builder tables. Kept in the dataset package (not backend/models.py) to
keep the module self-contained; registered via database.init_db. FKs reference
observation/farm/node/conversation by column only — no ORM relationships — so the
dataset layer stays decoupled from the domain models.
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base

# Dataset entry lifecycle.
NEW = "NEW"
VALIDATED = "VALIDATED"
EXPORTED = "EXPORTED"
ARCHIVED = "ARCHIVED"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DatasetEntry(Base):
    """One structured training record per observation (upserted as the
    observation completes). This is the raw material for future fine-tuning,
    vision training, and research."""

    __tablename__ = "dataset_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation_id: Mapped[str] = mapped_column(
        ForeignKey("observations.id"), unique=True, index=True
    )
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"))
    crop_type: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)

    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_long: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_moisture: Mapped[float | None] = mapped_column(Float, nullable=True)

    vision_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String, nullable=True)

    active_alerts: Mapped[list] = mapped_column(JSON, default=list)   # alert type strings
    labels: Mapped[list] = mapped_column(JSON, default=list)          # auto labels
    conversation_reference: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True
    )
    weather_reference: Mapped[str | None] = mapped_column(String, nullable=True)  # future

    quality_score: Mapped[int] = mapped_column(Integer, default=0)
    quality_reason: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default=NEW, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class DatasetExport(Base):
    """History of every export run (versioning + reproducibility)."""

    __tablename__ = "dataset_exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_version: Mapped[str] = mapped_column(String, unique=True, index=True)
    fmt: Mapped[str] = mapped_column(String)                 # jsonl | csv | parquet
    record_count: Mapped[int] = mapped_column(Integer)
    filters_used: Mapped[dict] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String)            # sha256 of the file
    path: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
