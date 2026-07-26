"""Pydantic schemas for the Dataset Builder API (kept in-module)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict

_orm = ConfigDict(from_attributes=True)


class DatasetEntryOut(BaseModel):
    model_config = _orm
    id: int
    observation_id: str
    farm_id: int
    node_id: str
    crop_type: str
    timestamp: datetime
    gps_lat: float | None
    gps_long: float | None
    temperature: float | None
    humidity: float | None
    soil_moisture: float | None
    vision_summary: str | None
    ai_summary: str | None
    image_path: str | None
    active_alerts: list[str]
    labels: list[str]
    conversation_reference: int | None
    weather_reference: str | None
    quality_score: int
    quality_reason: str
    status: str
    created_at: datetime


class ExportRequest(BaseModel):
    fmt: str = "jsonl"  # jsonl | csv | parquet
    farm_id: int | None = None
    crop_type: str | None = None
    min_quality: int | None = None
    status: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class ExportOut(BaseModel):
    model_config = _orm
    id: int
    dataset_version: str
    fmt: str
    record_count: int
    filters_used: dict
    checksum: str
    path: str
    created_at: datetime
