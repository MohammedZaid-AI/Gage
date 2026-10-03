"""AI facade: provider selection and the low-level model calls.

Everything about *which* model runs lives here. Grounded context assembly now
lives in services/farm_context.py + ai/prompt_builder.py, and the end-to-end
chat flow in ai/orchestrator.py — this module only owns provider wiring.
"""
import logging

from backend.ai.base import LLMProvider, SpeechProvider
from backend.ai.mock import MockLLMProvider, MockSpeechProvider
from backend.config import get_settings

logger = logging.getLogger("gage.ai")


def _select_llm() -> LLMProvider:
    """Map LLM_PROVIDER to an implementation. Add gemini/ollama/openai here only."""
    name = get_settings().llm_provider.lower()
    if name == "sarvam_finetuned":
        # Deliberately no fallback: if the configured model cannot load, startup
        # fails loudly instead of silently answering farmers with the mock.
        from backend.ai.providers.sarvam_llm import SarvamFinetunedLLMProvider  # lazy: torch/peft

        return SarvamFinetunedLLMProvider()
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


_llm = _select_llm()
_speech = _select_speech()


def detect_language(text: str) -> str:
    """Kannada if any Kannada-block codepoint (U+0C80–U+0CFF) is present, else English."""
    return "kn" if any("ಀ" <= ch <= "೿" for ch in text) else "en"


def complete(question: str, context: str, language: str) -> str:
    """Low-level: send an already-built prompt/context to the active LLM provider.
    Raises LLMError if the model could not answer. Blocking: call it off the
    event loop."""
    return _llm.answer(question, context, language)


def prompt_style() -> str:
    """'structured' or 'compact' — which prompt the active LLM expects."""
    return _llm.prompt_style


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
