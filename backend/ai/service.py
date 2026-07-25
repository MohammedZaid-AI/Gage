"""AI facade: provider selection, language detection, and context assembly.

Routers call `describe_image` and `answer_question`; everything about *which*
model runs lives here. Context is always scoped to a single farm so the
assistant grounds its answer in that farmer's own field, never someone else's.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.base import LLMProvider, VisionProvider
from backend.ai.mock import MockLLMProvider, MockVisionProvider
from backend.config import get_settings
from backend.models import Conversation, Farm, Observation

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


def summarize_observation(context: str, language: str = "en") -> str:
    """One-line agronomic summary of a single observation. Reuses the LLM provider
    interface (no new provider method) so it stays behind the same abstraction."""
    return _llm.answer(
        "In one short sentence, summarise the crop condition for the farmer.",
        context,
        language,
    )


def _recent_conversation(db: Session, farm_id: int, limit: int = 3) -> str:
    turns = list(
        db.execute(
            select(Conversation)
            .where(Conversation.farm_id == farm_id)
            .order_by(Conversation.timestamp.desc())
            .limit(limit)
        ).scalars()
    )
    if not turns:
        return ""
    lines = [f"Q: {t.question}\nA: {t.answer}" for t in reversed(turns)]
    return "\n\nPrevious conversation:\n" + "\n".join(lines)


def _build_context(db: Session, farm_id: int) -> str:
    """Assemble this farm's snapshot: identity, latest observation, sensors, GPS,
    and recent conversation."""
    farm = db.get(Farm, farm_id)
    header = f"Farm: {farm.name}" + (f", {farm.village}" if farm and farm.village else "")

    obs = db.execute(
        select(Observation)
        .where(Observation.farm_id == farm_id)
        .order_by(Observation.timestamp.desc())
        .limit(1)
    ).scalar_one_or_none()

    total = (
        db.query(Observation).filter(Observation.farm_id == farm_id).count()
    )
    if obs is None:
        return (
            f"{header}\n"
            f"No observations recorded yet for this farm. Total observations: {total}."
            + _recent_conversation(db, farm_id)
        )

    def fmt(v: float | None, unit: str) -> str:
        return f"{v}{unit}" if v is not None else "n/a"

    return (
        f"{header}\n"
        f"Latest observation ({obs.timestamp:%Y-%m-%d %H:%M} UTC, node {obs.node_id}):\n"
        f"- Vision: {obs.vision_summary or 'not analysed'}\n"
        f"- GPS: {fmt(obs.gps_lat, '')}, {fmt(obs.gps_long, '')}\n"
        f"- Temperature: {fmt(obs.temperature, ' C')}\n"
        f"- Humidity: {fmt(obs.humidity, ' %')}\n"
        f"- Soil moisture: {fmt(obs.soil_moisture, ' %')}\n"
        f"- Total observations for this farm: {total}"
        + _recent_conversation(db, farm_id)
    )


def answer_question(db: Session, farm_id: int, question: str) -> tuple[str, str]:
    """Return (answer, language) grounded in the given farm's field context."""
    language = detect_language(question)
    context = _build_context(db, farm_id)
    answer = _llm.answer(question, context, language)
    return answer, language
