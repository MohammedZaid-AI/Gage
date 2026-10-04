"""Groq-hosted GPT-OSS LLM provider via Groq's OpenAI-compatible endpoint.

Implements the shared `LLMProvider` interface. Language is *not* detected here —
the system prompt instructs the model to reply in whichever language the farmer
used, so English in → English out, Kannada in → Kannada out.
"""
import logging

from openai import OpenAI, OpenAIError

from backend.ai.base import LLMError, LLMProvider
from backend.config import get_settings

logger = logging.getLogger("gage.ai.groq")

_SYSTEM_PROMPT = (
    "You are Gage, an experienced agricultural field officer for sugarcane farmers "
    "in Karnataka. Behave like a seasoned agronomist, not a generic chatbot: reason "
    "from the farm's own evidence and never invent data. Follow the response contract "
    "and grounding rules given in the field context exactly — answer in Observation / "
    "Analysis / Confidence / Recommendations sections, keep Observed Facts separate "
    "from Inference and Recommendation, and if the evidence is insufficient say so "
    "instead of guessing. Reply in Kannada if the farmer wrote Kannada, else English."
)

_SUMMARY_PROMPT = (
    "You write the short status line shown on a sugarcane farmer's home screen. "
    "Using only the farm data given, write one or two plain sentences: the field's "
    "current state, and the single most important thing to watch or do if anything "
    "needs attention. No headings, no lists, no 'Observation / Analysis / "
    "Confidence / Recommendations' sections, and no numbers that are not in the "
    "data. Write in {language}."
)

_TIMEOUT_S = 60.0   # the SDK default is 600 s; a hung call should fail, not hold a worker


class GroqLLMProvider(LLMProvider):
    def __init__(self) -> None:
        s = get_settings()
        self._model = s.groq_model
        # The SDK requires a non-empty key to construct; a missing/invalid key
        # surfaces as an LLMError at call time rather than crashing boot.
        self._client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=s.groq_api_key or "not-set",
            timeout=_TIMEOUT_S,
            max_retries=2,
        )

    def answer(self, question: str, context: str, language: str) -> str:
        """Blocking network call: callers run it off the event loop (the chat and
        voice routers use a worker thread). Raises LLMError on any failure, so an
        error is never returned, shown or saved as if it were an answer."""
        # `language` is ignored on purpose — the model matches the user's language.
        return self._complete([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "system", "content": f"Current field context:\n{context}"},
            {"role": "user", "content": question},
        ])

    def summarize(self, context: str, language: str) -> str:
        """Home-screen status: its own short prompt, not the four-section answer
        contract of _SYSTEM_PROMPT. Raises LLMError."""
        lang = "Kannada (Kannada script)" if language == "kn" else "English"
        return self._complete([
            {"role": "system", "content": _SUMMARY_PROMPT.format(language=lang)},
            {"role": "user", "content": f"Farm data:\n{context}"},
        ])

    def _complete(self, messages: list[dict]) -> str:
        try:
            resp = self._client.chat.completions.create(model=self._model, messages=messages)
        except OpenAIError as exc:
            logger.exception("Groq request failed (model=%s)", self._model)
            raise LLMError(f"Groq request failed: {type(exc).__name__}") from exc
        except Exception as exc:  # network / unexpected
            logger.exception("Unexpected error calling Groq")
            raise LLMError(f"Groq request failed: {type(exc).__name__}") from exc
        text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        if not text:
            raise LLMError("Groq returned an empty answer")
        return text
