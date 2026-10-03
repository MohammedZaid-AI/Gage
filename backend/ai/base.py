"""Provider interfaces. Implement these to add a new AI backend."""
from abc import ABC, abstractmethod


class LLMError(RuntimeError):
    """The model could not produce an answer. Raised instead of returning text,
    so a failure is never shown to a farmer or saved as if it were advice."""


class LLMProvider(ABC):
    """Answers a farmer's question given assembled field context."""

    # Which prompt the orchestrator builds for this provider: "structured" (the
    # full Crop Doctor contract, for large instruction-following models) or
    # "compact" (farm readings + knowledge only, for a small fine-tuned model
    # trained on a short context window).
    prompt_style: str = "structured"

    @abstractmethod
    def answer(self, question: str, context: str, language: str) -> str:
        """Return the answer text, or raise LLMError. Never return an error
        message disguised as an answer."""


class SpeechProvider(ABC):
    """Speech-to-text and text-to-speech (e.g. Sarvam AI) for the voice loop."""

    @abstractmethod
    def transcribe(self, audio: bytes, language: str | None = None) -> tuple[str, str]:
        """Return (transcript, language-code) for the spoken audio."""

    @abstractmethod
    def synthesize(self, text: str, language: str) -> bytes:
        """Return audio bytes (a playable file) speaking `text` in `language`."""
