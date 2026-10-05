"""AI facade: provider selection and the low-level model calls.

Everything about *which* model runs lives here. Grounded context assembly now
lives in services/farm_context.py + ai/prompt_builder.py, and the end-to-end
chat flow in ai/orchestrator.py — this module only owns provider wiring.
"""
import logging
import threading

from backend.ai.base import LLMProvider, LLMUnavailable, SpeechProvider
from backend.ai.mock import MockLLMProvider, MockSpeechProvider
from backend.config import get_settings

logger = logging.getLogger("gage.ai")


# Answer engines a chat request may pick (ChatRequest.provider). "mock" is only
# for offline tests and is reachable only as the LLM_PROVIDER default.
ENGINES = ("groq", "sarvam_finetuned")

_engines: dict[str, LLMProvider] = {}       # one instance per engine, created on first use
_engine_locks = {name: threading.Lock() for name in (*ENGINES, "mock")}


def default_engine() -> str:
    return get_settings().llm_provider.lower()


def _create(name: str) -> LLMProvider:
    """Build an engine. Add gemini/ollama/openai here only."""
    if name == "sarvam_finetuned":
        # Loads the base model + LoRA adapter onto the GPU (tens of seconds, ~2 GB
        # of VRAM). Deliberately no fallback: a failure is reported to the farmer
        # as "engine unavailable", never answered by another model.
        try:
            from backend.ai.providers.sarvam_llm import SarvamFinetunedLLMProvider  # lazy: torch/peft

            return SarvamFinetunedLLMProvider()
        except Exception as exc:
            logger.exception("fine-tuned engine could not be loaded")
            raise LLMUnavailable(f"The fine-tuned engine (sarvam_finetuned) is unavailable: "
                                 f"{type(exc).__name__}: {exc}") from exc
    if name == "groq":
        from backend.ai.providers.groq_provider import GroqLLMProvider  # lazy: only import SDK when used

        return GroqLLMProvider()
    if name == "mock":
        return MockLLMProvider()
    raise LLMUnavailable(f"Unknown answer engine {name!r}; choose one of {', '.join(ENGINES)}")


def get_llm(engine: str | None = None) -> LLMProvider:
    """The engine named `engine` (default: LLM_PROVIDER), created on its first
    use and kept: the fine-tuned model is loaded at most once, by the first
    request that asks for it, never at server startup. Raises LLMUnavailable."""
    name = (engine or default_engine()).lower()
    inst = _engines.get(name)
    if inst is not None:
        return inst
    lock = _engine_locks.get(name)
    if lock is None:
        raise LLMUnavailable(f"Unknown answer engine {name!r}; choose one of {', '.join(ENGINES)}")
    with lock:                       # concurrent first requests load it once
        if name not in _engines:
            _engines[name] = _create(name)
    return _engines[name]


def _select_speech() -> SpeechProvider:
    """Map SPEECH_PROVIDER to an implementation. Add new speech backends here only."""
    name = get_settings().speech_provider.lower()
    if name == "sarvam":
        from backend.ai.providers.sarvam_provider import SarvamSpeechProvider  # lazy

        return SarvamSpeechProvider()
    if name != "mock":
        logger.warning("speech provider %r not implemented yet; using mock", name)
    return MockSpeechProvider()


_speech = _select_speech()


def detect_language(text: str) -> str:
    """Kannada if any Kannada-block codepoint (U+0C80–U+0CFF) is present, else English."""
    return "kn" if any("ಀ" <= ch <= "೿" for ch in text) else "en"


def complete(question: str, context: str, language: str, engine: str | None = None) -> str:
    """Low-level: send an already-built prompt/context to an answer engine
    (default LLM_PROVIDER). Raises LLMError if it could not answer (LLMUnavailable
    if the engine cannot be loaded). Blocking: call it off the event loop."""
    return get_llm(engine).answer(question, context, language)


def prompt_style(engine: str | None = None) -> str:
    """'structured' or 'compact' — which prompt the engine expects."""
    return get_llm(engine).prompt_style


def transcribe(audio: bytes, language: str | None = None) -> tuple[str, str]:
    """Speech -> (transcript, language) via the active speech provider."""
    return _speech.transcribe(audio, language)


def synthesize(text: str, language: str) -> bytes:
    """Text -> spoken audio bytes via the active speech provider."""
    return _speech.synthesize(text, language)


def summarize_observation(context: str, language: str = "en") -> str:
    """One or two plain sentences on the farm's state, via the active provider's
    own summary prompt (not the four-section answer format). Raises LLMError."""
    return get_llm().summarize(context, language)
