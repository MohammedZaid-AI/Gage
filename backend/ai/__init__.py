"""AI abstraction layer.

Provider wiring lives in `service`; grounded context assembly in
`services/farm_context` + `prompt_builder`; the end-to-end chat flow in
`orchestrator`. Swapping in Gemini, OpenAI, Ollama, Qwen2.5-VL or Gemma later is
a change in `service` / `providers` only.
"""
from backend.ai.base import LLMProvider, SpeechProvider, VisionProvider
from backend.ai.service import (
    complete,
    analyze_image,
    detect_language,
    summarize_observation,
    synthesize,
    transcribe,
)

__all__ = [
    "LLMProvider",
    "SpeechProvider",
    "VisionProvider",
    "complete",
    "analyze_image",
    "detect_language",
    "summarize_observation",
    "synthesize",
    "transcribe",
]
