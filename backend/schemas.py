"""Pydantic v2 request/response schemas."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_orm = ConfigDict(from_attributes=True)


# --- auth ---
class RegisterRequest(BaseModel):
    phone: str = Field(min_length=4, max_length=20)
    password: str = Field(min_length=4)
    name: str | None = None
    language: str | None = None  # "kn" | "en"


class LoginRequest(BaseModel):
    phone: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class FarmerOut(BaseModel):
    model_config = _orm
    id: int
    phone: str
    name: str | None
    language: str


# --- farm / node ---
class FarmCreate(BaseModel):
    name: str
    crop_type: str = "sugarcane"
    village: str | None = None
    area_acres: float | None = None


class FarmOut(BaseModel):
    model_config = _orm
    id: int
    name: str
    crop_type: str
    village: str | None
    area_acres: float | None
    created_at: datetime


class NodeCreate(BaseModel):
    id: str  # hardware/device id, chosen by the deployer
    name: str | None = None
    location: str | None = None


class NodeHealthOut(BaseModel):
    model_config = _orm
    status: str
    last_seen: datetime | None
    battery: float | None
    wifi_strength: int | None
    firmware_version: str | None
    gps_available: bool | None
    camera_available: bool | None
    storage_available: bool | None


class NodeOut(BaseModel):
    model_config = _orm
    id: str
    farm_id: int
    name: str | None
    location: str | None
    # The device key, returned only when it is created or rotated (it is stored
    # hashed and cannot be shown again). None in listings.
    api_key: str | None = None
    created_at: datetime
    health: NodeHealthOut | None = None


# --- node telemetry inputs (device -> backend) ---
class SensorIn(BaseModel):
    temperature: float | None = None
    humidity: float | None = None
    soil_moisture: float | None = None
    battery: float | None = None
    timestamp: datetime | None = None


class HeartbeatIn(BaseModel):
    source: str = "esp32"  # esp32 | phone
    battery: float | None = None
    wifi_strength: int | None = None
    firmware_version: str | None = None
    gps_available: bool | None = None
    camera_available: bool | None = None
    storage_available: bool | None = None


class SensorReadingOut(BaseModel):
    model_config = _orm
    id: int
    node_id: str
    farm_id: int
    temperature: float | None
    humidity: float | None
    soil_moisture: float | None
    battery: float | None
    timestamp: datetime
    observation_id: str | None


class AlertOut(BaseModel):
    model_config = _orm
    id: int
    farm_id: int
    node_id: str | None
    type: str
    severity: str
    message: str
    value: float | None
    resolved: bool
    created_at: datetime
    resolved_at: datetime | None = None
    resolution: str | None = None


# --- observation ---
class ObservationOut(BaseModel):
    model_config = _orm
    id: str
    farm_id: int
    node_id: str
    timestamp: datetime
    gps_lat: float | None
    gps_long: float | None
    image_path: str | None
    temperature: float | None
    humidity: float | None
    soil_moisture: float | None
    ai_summary: str | None


# --- chat ---
class ChatRequest(BaseModel):
    farm_id: int
    question: str
    # Answer engine for this question; missing -> LLM_PROVIDER from .env.
    provider: Literal["groq", "sarvam_finetuned"] | None = None


class ChatResponse(BaseModel):
    question: str
    answer: str
    language: str
    # Specific claims the grounding check could not find in the model's context
    # (the answer is already prefixed with a caveat when this is non-empty).
    unsupported_claims: list[str] = []
    # Groq grounding check: checked | unavailable | skipped (token budget).
    fact_check: str | None = None
    provider: str | None = None          # the engine that wrote this answer
    answer_seconds: float | None = None  # time in that engine
    fact_check_seconds: float | None = None
    # The model's own text before any caveat or note was added.
    raw_answer: str | None = None
    # Retrieved knowledge chunks: source document, section and score.
    sources: list[dict] = []


# --- voice ---
class VoiceAnswer(BaseModel):
    transcript: str
    answer: str
    language: str
    audio_base64: str  # spoken answer (WAV); empty if TTS unavailable


class SpeakRequest(BaseModel):
    text: str
    language: str | None = None


class SpeakResponse(BaseModel):
    language: str
    audio_base64: str


# --- farm intelligence ---
class HealthOut(BaseModel):
    score: int
    status: str
    reasons: list[str]


class TrendOut(BaseModel):
    metric: str
    current: float
    previous: float
    delta: float
    direction: str
    unit: str
    days_ago: int


class SensorSnapshot(BaseModel):
    temperature: float | None
    humidity: float | None
    soil_moisture: float | None


class FarmSummaryOut(BaseModel):
    farm_id: int
    name: str
    crop_type: str
    location: str
    health: HealthOut
    last_observation_time: datetime | None
    sensor_snapshot: SensorSnapshot
    trends: list[TrendOut]
    active_alerts: list[AlertOut]
    ai_summary: str | None
    latest_observation: ObservationOut | None
