"""Database models. Ownership chain: Farmer -> Farm -> Node -> Observation.

Design notes:
- Node holds *identity* (id, api_key, location); mutable runtime telemetry lives
  in NodeHealth (current snapshot, 1:1) and NodeHeartbeat (append-only history).
- SensorReading is the raw ESP32 ingest log (source of truth for sensor history).
  An Observation carries the merged snapshot the AI reads (denormalized read
  model) and links back to the reading(s) that fed it via SensorReading.observation_id.
- The phone reports one image + GPS; the ESP32 reports one temperature/humidity/
  soil triple. The backend merges the two into a single Observation per capture.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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
    """A monitoring node (Android phone + ESP32) deployed in a farm. Identity only;
    runtime telemetry is in NodeHealth / NodeHeartbeat."""

    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # hardware/device id
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    api_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    farm: Mapped[Farm] = relationship(back_populates="nodes")
    health: Mapped["NodeHealth | None"] = relationship(
        back_populates="node", uselist=False, cascade="all, delete-orphan"
    )
    observations: Mapped[list["Observation"]] = relationship(
        back_populates="node", cascade="all, delete-orphan"
    )


class NodeHealth(Base):
    """Current runtime snapshot for a node (upserted on every heartbeat)."""

    __tablename__ = "node_health"

    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String, default="online")  # online | offline
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    battery: Mapped[float | None] = mapped_column(Float, nullable=True)  # percent
    wifi_strength: Mapped[int | None] = mapped_column(Integer, nullable=True)  # dBm
    firmware_version: Mapped[str | None] = mapped_column(String, nullable=True)
    gps_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    camera_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    storage_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    node: Mapped[Node] = relationship(back_populates="health")


class NodeHeartbeat(Base):
    """Append-only heartbeat log from ESP32 or phone."""

    __tablename__ = "node_heartbeats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), index=True)
    source: Mapped[str] = mapped_column(String)  # esp32 | phone
    battery: Mapped[float | None] = mapped_column(Float, nullable=True)
    wifi_strength: Mapped[int | None] = mapped_column(Integer, nullable=True)
    firmware_version: Mapped[str | None] = mapped_column(String, nullable=True)
    gps_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    camera_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    storage_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class SensorReading(Base):
    """Raw ESP32 sensor push. Linked to the Observation it was merged into (if any)."""

    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), index=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_moisture: Mapped[float | None] = mapped_column(Float, nullable=True)
    battery: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    observation_id: Mapped[str | None] = mapped_column(
        ForeignKey("observations.id"), nullable=True
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
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # LLM, on merge

    farm: Mapped[Farm] = relationship(back_populates="observations")
    node: Mapped[Node] = relationship(back_populates="observations")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    node_id: Mapped[str | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    type: Mapped[str] = mapped_column(String, index=True)  # humidity_high, soil_low, ...
    severity: Mapped[str] = mapped_column(String, default="warning")  # info|warning|critical
    message: Mapped[str] = mapped_column(String)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


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
