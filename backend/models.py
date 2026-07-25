"""Database models. Ownership chain: Farmer -> Farm -> Node -> Observation.

Conversations belong to a Farm (and the Farmer who asked). Sensor readings live
directly on the Observation for V1: a node reports exactly one temperature /
humidity / soil-moisture triple per capture, so a separate `sensor_readings`
table would be normalization without a payoff. Split it out only when a node's
set of sensors starts varying over time.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Farmer(Base):
    __tablename__ = "farmers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str] = mapped_column(String(5), default="kn")  # kn | en
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    farms: Mapped[list["Farm"]] = relationship(
        back_populates="farmer", cascade="all, delete-orphan"
    )


class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farmer_id: Mapped[int] = mapped_column(ForeignKey("farmers.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    village: Mapped[str | None] = mapped_column(String, nullable=True)
    area_acres: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    farmer: Mapped[Farmer] = relationship(back_populates="farms")
    nodes: Mapped[list["Node"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    observations: Mapped[list["Observation"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )


class Node(Base):
    """A monitoring node deployed in a farm (Android phone + ESP32 + sensors)."""

    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # hardware/device id
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active | offline
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    farm: Mapped[Farm] = relationship(back_populates="nodes")
    observations: Mapped[list["Observation"]] = relationship(
        back_populates="node", cascade="all, delete-orphan"
    )


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_long: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_moisture: Mapped[float | None] = mapped_column(Float, nullable=True)
    vision_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # per-image
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # LLM, on demand

    farm: Mapped[Farm] = relationship(back_populates="observations")
    node: Mapped[Node] = relationship(back_populates="observations")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    farmer_id: Mapped[int] = mapped_column(ForeignKey("farmers.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(5), default="kn")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now)

    farm: Mapped[Farm] = relationship(back_populates="conversations")
