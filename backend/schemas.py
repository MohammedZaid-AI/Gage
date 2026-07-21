"""Pydantic request/response schemas."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    inspection_id: int | None
    image_path: str | None
    gps_lat: float | None
    gps_long: float | None
    temperature: float | None
    humidity: float | None
    soil_moisture: float | None
    timestamp: datetime
    ai_summary: str | None


class InspectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    ended_at: datetime | None
    total_observations: int


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    question: str
    answer: str
    language: str


class RobotCommandResponse(BaseModel):
    command: str
    status: str = "ok"
