"""AI abstraction layer.

Business logic depends only on the `VisionProvider` / `LLMProvider` interfaces
and the `describe_image` / `answer_question` helpers below. Swapping in Gemini,
OpenAI, Ollama, Qwen2.5-VL or Gemma later is a change *here only*.
"""
from backend.ai.base import LLMProvider, VisionProvider
from backend.ai.service import (
    answer_question,
    describe_image,
    detect_language,
    summarize_observation,
)

__all__ = [
    "LLMProvider",
    "VisionProvider",
    "answer_question",
    "describe_image",
    "detect_language",
    "summarize_observation",
]
