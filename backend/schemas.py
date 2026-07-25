"""Pydantic v2 request/response schemas."""
from datetime import datetime

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
    village: str | None = None
    area_acres: float | None = None


class FarmOut(BaseModel):
    model_config = _orm
    id: int
    name: str
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
    api_key: str  # the owner needs this to provision the device
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
    vision_summary: str | None
    ai_summary: str | None


# --- chat ---
class ChatRequest(BaseModel):
    farm_id: int
    question: str


class ChatResponse(BaseModel):
    question: str
    answer: str
    language: str
