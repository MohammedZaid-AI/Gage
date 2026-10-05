"""Provider interfaces. Implement these to add a new AI backend."""
from abc import ABC, abstractmethod


class LLMError(RuntimeError):
    """The model could not produce an answer. Raised instead of returning text,
    so a failure is never shown to a farmer or saved as if it were advice."""


class LLMUnavailable(LLMError):
    """The requested answer engine cannot run (model or GPU missing, failed to
    load, unknown name). Reported as such; never answered by another engine."""


class LLMBusy(LLMError):
    """The model service is rate-limited; `retry_after` says how long to wait."""

    def __init__(self, message: str, retry_after: float):
        super().__init__(message)
        self.retry_after = retry_after


class LLMProvider(ABC):
    """Answers a farmer's question given assembled field context."""

    # Which prompt the orchestrator builds for this provider: "structured" (the
    # full Crop Doctor contract with farm data, for large instruction-following
    # models) or "compact" (retrieved knowledge + the farmer's question only, no
    # sensor readings, for the small fine-tuned model trained on that shape).
    prompt_style: str = "structured"

    @abstractmethod
    def answer(self, question: str, context: str, language: str) -> str:
        """Return the answer text, or raise LLMError. Never return an error
        message disguised as an answer."""

    def summarize(self, context: str, language: str) -> str:
        """One or two plain sentences on the farm's current state (for the Home
        screen), or raise LLMError. Providers whose answer() imposes a long
        answer format should override this with their own short prompt."""
        return self.answer(SUMMARY_REQUEST, context, language)


SUMMARY_REQUEST = ("In one or two plain sentences, describe the farm's current state "
                   "for the farmer. No headings or lists.")


class SpeechProvider(ABC):
    """Speech-to-text and text-to-speech (e.g. Sarvam AI) for the voice loop."""

    @abstractmethod
    def transcribe(self, audio: bytes, language: str | None = None) -> tuple[str, str]:
        """Return (transcript, language-code) for the spoken audio."""

    @abstractmethod
    def synthesize(self, text: str, language: str) -> bytes:
        """Return audio bytes (a playable file) speaking `text` in `language`."""
