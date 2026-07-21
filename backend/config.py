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
    groq_model: str = "gpt-oss-120b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
