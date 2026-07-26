"""Provider interfaces. Implement these to add a new AI backend."""
from abc import ABC, abstractmethod


class VisionProvider(ABC):
    """Turns an image (raw bytes) into a plain-language agronomic description."""

    @abstractmethod
    def describe(self, image_bytes: bytes) -> str: ...


class LLMProvider(ABC):
    """Answers a farmer's question given assembled field context."""

    @abstractmethod
    def answer(self, question: str, context: str, language: str) -> str: ...


class SpeechProvider(ABC):
    """Speech-to-text and text-to-speech (e.g. Sarvam AI) for the voice loop."""

    @abstractmethod
    def transcribe(self, audio: bytes, language: str | None = None) -> tuple[str, str]:
        """Return (transcript, language-code) for the spoken audio."""

    @abstractmethod
    def synthesize(self, text: str, language: str) -> bytes:
        """Return audio bytes (a playable file) speaking `text` in `language`."""
