"""AI abstraction layer.

Provider wiring lives in `service`; grounded context assembly in
`services/farm_context` + `prompt_builder`; the end-to-end chat flow in
`orchestrator`. Swapping in Gemini, OpenAI, Ollama, Qwen2.5-VL or Gemma later is
a change in `service` / `providers` only.
"""
from backend.ai.base import LLMProvider, VisionProvider
from backend.ai.service import (
    complete,
    describe_image,
    detect_language,
    summarize_observation,
)

__all__ = [
    "LLMProvider",
    "VisionProvider",
    "complete",
    "describe_image",
    "detect_language",
    "summarize_observation",
]
