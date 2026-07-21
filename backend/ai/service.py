"""AI facade: provider selection, language detection, and context assembly.

Routers call `describe_image` and `answer_question`; everything about *which*
model runs lives here.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.base import LLMProvider, VisionProvider
from backend.ai.mock import MockLLMProvider, MockVisionProvider
from backend.config import get_settings
from backend.models import Observation

logger = logging.getLogger("gage.ai")


def _select_vision() -> VisionProvider:
    s = get_settings()
    if s.vision_provider != "mock":
        # ponytail: real providers (gemini/openai/qwen) plug in here; fall back
        # to mock until one is wired + keyed so the demo never breaks.
        logger.warning("vision provider %r not implemented yet; using mock", s.vision_provider)
    return MockVisionProvider()


def _select_llm() -> LLMProvider:
    s = get_settings()
    if s.llm_provider != "mock":
        logger.warning("llm provider %r not implemented yet; using mock", s.llm_provider)
    return MockLLMProvider()


_vision = _select_vision()
_llm = _select_llm()


def detect_language(text: str) -> str:
    """Kannada if any Kannada-block codepoint (U+0C80–U+0CFF) is present, else English."""
    return "kn" if any("ಀ" <= ch <= "೿" for ch in text) else "en"


def describe_image(image_bytes: bytes) -> str:
    return _vision.describe(image_bytes)


def _build_context(db: Session) -> str:
    """Assemble the latest observation + sensor snapshot the assistant reasons over."""
    obs = db.execute(
        select(Observation).order_by(Observation.timestamp.desc()).limit(1)
    ).scalar_one_or_none()

    total = db.query(Observation).count()
    if obs is None:
        return f"No observations recorded yet. Total inspections logged: {total}."

    def fmt(v: float | None, unit: str) -> str:
        return f"{v}{unit}" if v is not None else "n/a"

    return (
        f"Latest observation ({obs.timestamp:%Y-%m-%d %H:%M} UTC):\n"
        f"- Description: {obs.ai_summary or 'not analysed'}\n"
        f"- GPS: {fmt(obs.gps_lat, '')}, {fmt(obs.gps_long, '')}\n"
        f"- Temperature: {fmt(obs.temperature, ' C')}\n"
        f"- Humidity: {fmt(obs.humidity, ' %')}\n"
        f"- Soil moisture: {fmt(obs.soil_moisture, ' %')}\n"
        f"- Total observations so far: {total}"
    )


def answer_question(db: Session, question: str) -> tuple[str, str]:
    """Return (answer, language) grounded in current field context."""
    language = detect_language(question)
    context = _build_context(db)
    answer = _llm.answer(question, context, language)
    return answer, language
