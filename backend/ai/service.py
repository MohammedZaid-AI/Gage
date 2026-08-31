"""AI facade: provider selection and the low-level model calls.

Everything about *which* model runs lives here. Grounded context assembly now
lives in services/farm_context.py + ai/prompt_builder.py, and the end-to-end
chat flow in ai/orchestrator.py — this module only owns provider wiring.
"""
import logging

from backend.ai.base import VisionResult, LLMProvider, SpeechProvider, VisionProvider
from backend.ai.mock import MockLLMProvider, MockSpeechProvider, MockVisionProvider
from backend.config import get_settings

logger = logging.getLogger("gage.ai")


def _select_vision() -> VisionProvider:
    """Map VISION_PROVIDER to an implementation. The model is loaded exactly once,
    here, at import time — never per request."""
    name = get_settings().vision_provider.lower()
    if name == "tflite":
        from backend.ai.providers.tflite_vision import TFLiteVisionProvider  # lazy

        try:
            return TFLiteVisionProvider()
        except Exception:
            # A missing model file or runtime must not take the API down; the
            # mock abstains from every diagnosis, so nothing downstream guesses.
            logger.exception("tflite vision provider failed to load; falling back to mock")
            return MockVisionProvider()
    if name != "mock":
        logger.warning("vision provider %r not implemented yet; using mock", name)
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


def _select_speech() -> SpeechProvider:
    """Map SPEECH_PROVIDER to an implementation. Add new speech backends here only."""
    name = get_settings().speech_provider.lower()
    if name == "sarvam":
        from backend.ai.providers.sarvam_provider import SarvamSpeechProvider  # lazy

        return SarvamSpeechProvider()
    if name != "mock":
        logger.warning("speech provider %r not implemented yet; using mock", name)
    return MockSpeechProvider()


_vision = _select_vision()
_llm = _select_llm()
_speech = _select_speech()


def detect_language(text: str) -> str:
    """Kannada if any Kannada-block codepoint (U+0C80–U+0CFF) is present, else English."""
    return "kn" if any("ಀ" <= ch <= "೿" for ch in text) else "en"


def analyze_image(image_bytes: bytes) -> VisionResult:
    """Vision finding for one image: prose + (label, confidence, abstained)."""
    return _vision.analyze(image_bytes)


def complete(question: str, context: str, language: str) -> str:
    """Low-level: send an already-built prompt/context to the active LLM provider."""
    return _llm.answer(question, context, language)


def transcribe(audio: bytes, language: str | None = None) -> tuple[str, str]:
    """Speech -> (transcript, language) via the active speech provider."""
    return _speech.transcribe(audio, language)


def synthesize(text: str, language: str) -> bytes:
    """Text -> spoken audio bytes via the active speech provider."""
    return _speech.synthesize(text, language)


def summarize_observation(context: str, language: str = "en") -> str:
    """One-line agronomic summary of a single observation. Reuses the LLM provider
    interface (no new provider method) so it stays behind the same abstraction."""
    return complete(
        "In one short sentence, summarise the crop condition for the farmer.",
        context,
        language,
    )
