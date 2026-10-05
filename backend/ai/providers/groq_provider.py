"""Groq-hosted GPT-OSS LLM provider via Groq's OpenAI-compatible endpoint.

Implements the shared `LLMProvider` interface. Language is *not* detected here —
the system prompt instructs the model to reply in whichever language the farmer
used, so English in → English out, Kannada in → Kannada out.

All calls go through ai/groq_client.call, which keeps the per-model token
budget. The answer is never skipped by the budget; a summary can be.
"""
import logging
import time

from backend.ai import groq_client
from backend.ai.base import LLMBusy, LLMError, LLMProvider
from backend.config import get_settings

logger = logging.getLogger("gage.ai.groq")

# Short on purpose: the persona and the full response contract are in the
# field context (prompt_builder), so they are not sent twice.
_SYSTEM_PROMPT = (
    "You are Gage, an agricultural field officer for sugarcane farmers in Karnataka. "
    "Follow the response contract and rules in the field context exactly."
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
        self._model = get_settings().groq_model

    def answer(self, question: str, context: str, language: str) -> str:
        """Blocking network call: callers run it off the event loop (the chat and
        voice routers use a worker thread). Raises LLMError on any failure, so an
        error is never returned, shown or saved as if it were an answer.

        Rate limited (429): if Groq's wait is under GROQ_ANSWER_RETRY_MAX_WAIT_S,
        wait it out and retry once; otherwise raise LLMBusy with the wait."""
        # `language` is ignored on purpose — the model matches the user's language.
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "system", "content": f"Current field context:\n{context}"},
            {"role": "user", "content": question},
        ]
        max_wait = get_settings().groq_answer_retry_max_wait_s
        try:
            return self._complete("answer", messages)
        except groq_client.GroqRateLimited as exc:
            if exc.retry_after >= max_wait:
                raise LLMBusy(f"Groq is rate-limited ({exc.limit}); try again in about "
                              f"{exc.retry_after:.0f} seconds", exc.retry_after) from exc
            logger.info("answer rate-limited; waiting %.1fs and retrying once", exc.retry_after)
            time.sleep(exc.retry_after + 0.5)
        try:
            return self._complete("answer", messages)
        except groq_client.GroqRateLimited as exc:
            raise LLMBusy(f"Groq is still rate-limited ({exc.limit}); try again in about "
                          f"{exc.retry_after:.0f} seconds", exc.retry_after) from exc

    def summarize(self, context: str, language: str) -> str:
        """Home-screen status: its own short prompt, not the four-section answer
        contract. Lowest priority for the token budget. Raises LLMError."""
        lang = "Kannada (Kannada script)" if language == "kn" else "English"
        try:
            return self._complete("summary", [
                {"role": "system", "content": _SUMMARY_PROMPT.format(language=lang)},
                {"role": "user", "content": f"Farm data:\n{context}"},
            ])
        except groq_client.GroqRateLimited as exc:
            raise LLMBusy(f"summary rate-limited ({exc.limit})", exc.retry_after) from exc

    def _complete(self, purpose: str, messages: list[dict]) -> str:
        try:
            return groq_client.call(purpose, messages, model=self._model, timeout=_TIMEOUT_S)
        except groq_client.GroqRateLimited:
            raise
        except groq_client.GroqUnavailable as exc:
            logger.warning("Groq %s failed (model=%s): %s", purpose, self._model, exc)
            raise LLMError(f"Groq request failed: {exc}") from exc
