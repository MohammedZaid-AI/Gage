"""AI abstraction layer.

Provider wiring lives in `service`; grounded context assembly in
`services/farm_context` + `prompt_builder`; the end-to-end chat flow in
`orchestrator`. Swapping in Gemini, OpenAI, Ollama or Gemma later is a change in
`service` / `providers` only.
"""
from backend.ai.base import LLMProvider, SpeechProvider
from backend.ai.service import (
    complete,
    detect_language,
    summarize_observation,
    synthesize,
    transcribe,
)

__all__ = [
    "LLMProvider",
    "SpeechProvider",
    "complete",
    "detect_language",
    "summarize_observation",
    "synthesize",
    "transcribe",
]
