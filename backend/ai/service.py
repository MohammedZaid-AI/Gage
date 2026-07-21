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
from backend.models import Conversation, Inspection, Observation

logger = logging.getLogger("gage.ai")


def _select_vision() -> VisionProvider:
    s = get_settings()
    if s.vision_provider != "mock":
        # ponytail: real providers (gemini/openai/qwen) plug in here; fall back
        # to mock until one is wired + keyed so the demo never breaks.
        logger.warning("vision provider %r not implemented yet; using mock", s.vision_provider)
    return MockVisionProvider()


def _select_llm() -> LLMProvider:
    """Map LLM_PROVIDER to an implementation. Add gemini/ollama/openai here only."""
    name = get_settings().llm_provider.lower()
    if name == "groq":
        from backend.ai.providers.groq_provider import GroqLLMProvider  # lazy: only import SDK when used

        return GroqLLMProvider()
    if name != "mock":
        logger.warning("llm provider %r not implemented yet; using mock", name)
    return MockLLMProvider()


_vision = _select_vision()
_llm = _select_llm()


def detect_language(text: str) -> str:
    """Kannada if any Kannada-block codepoint (U+0C80–U+0CFF) is present, else English."""
    return "kn" if any("ಀ" <= ch <= "೿" for ch in text) else "en"


def describe_image(image_bytes: bytes) -> str:
    return _vision.describe(image_bytes)


def _inspection_status(db: Session) -> str:
    active = db.execute(
        select(Inspection).where(Inspection.ended_at.is_(None))
    ).scalars().first()
    return f"active (session #{active.id})" if active else "no active inspection"


def _recent_conversation(db: Session, limit: int = 3) -> str:
    turns = list(
        db.execute(
            select(Conversation).order_by(Conversation.timestamp.desc()).limit(limit)
        ).scalars()
    )
    if not turns:
        return ""
    lines = [f"Q: {t.question}\nA: {t.answer}" for t in reversed(turns)]
    return "\n\nPrevious conversation:\n" + "\n".join(lines)


def _build_context(db: Session) -> str:
    """Assemble the field snapshot the assistant reasons over: latest observation,
    sensors, GPS, inspection status, and recent conversation."""
    status = _inspection_status(db)
    obs = db.execute(
        select(Observation).order_by(Observation.timestamp.desc()).limit(1)
    ).scalar_one_or_none()

    total = db.query(Observation).count()
    if obs is None:
        return (
            f"Inspection status: {status}.\n"
            f"No observations recorded yet. Total observations: {total}."
            + _recent_conversation(db)
        )

    def fmt(v: float | None, unit: str) -> str:
        return f"{v}{unit}" if v is not None else "n/a"

    return (
        f"Inspection status: {status}\n"
        f"Latest observation ({obs.timestamp:%Y-%m-%d %H:%M} UTC):\n"
        f"- Description: {obs.ai_summary or 'not analysed'}\n"
        f"- GPS: {fmt(obs.gps_lat, '')}, {fmt(obs.gps_long, '')}\n"
        f"- Temperature: {fmt(obs.temperature, ' C')}\n"
        f"- Humidity: {fmt(obs.humidity, ' %')}\n"
        f"- Soil moisture: {fmt(obs.soil_moisture, ' %')}\n"
        f"- Total observations so far: {total}"
        + _recent_conversation(db)
    )


def answer_question(db: Session, question: str) -> tuple[str, str]:
    """Return (answer, language) grounded in current field context."""
    language = detect_language(question)
    context = _build_context(db)
    answer = _llm.answer(question, context, language)
    return answer, language
