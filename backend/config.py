"""Application configuration loaded from environment / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./storage/observations.db"
    image_dir: str = "./storage/images"

    vision_provider: str = "mock"
    llm_provider: str = "mock"

    gemini_api_key: str = ""
    openai_api_key: str = ""

    # Groq (OpenAI-compatible). Model is configurable; defaults to GPT-OSS 120B.
    groq_api_key: str = ""
    # Groq namespaces the GPT-OSS models — the id is "openai/gpt-oss-120b", not "gpt-oss-120b".
    groq_model: str = "openai/gpt-oss-120b"

    # Speech (STT + TTS). mock | sarvam. Sarvam handles Kannada/English voice.
    speech_provider: str = "mock"
    sarvam_api_key: str = ""
    sarvam_stt_model: str = "saarika:v2"
    sarvam_tts_model: str = "bulbul:v2"
    sarvam_speaker: str = "anushka"

    # Auth. jwt_secret MUST be overridden in production via the environment.
    jwt_secret: str = "dev-insecure-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Demo farmer/farm/node seeded on startup so the dashboard runs out of the box.
    # ponytail: remove once real farmer onboarding exists.
    seed_demo: bool = True

    # Observation merge: an image and a sensor reading from the same node within
    # this window are merged into one observation.
    merge_window_seconds: int = 60

    # A node is considered offline if its last heartbeat is older than this.
    offline_seconds: int = 180

    # Alert rule thresholds. ponytail: global constants for V1; make them
    # per-crop / per-farm rows when agronomy demands it.
    humidity_max: float = 85.0       # % -> too humid (disease risk)
    soil_moisture_min: float = 20.0  # % -> too dry (water stress)
    temperature_max: float = 40.0    # C -> heat stress
    low_battery_percent: float = 20.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
