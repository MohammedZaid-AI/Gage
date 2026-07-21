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
