"""Groq-hosted GPT-OSS LLM provider via Groq's OpenAI-compatible endpoint.

Implements the shared `LLMProvider` interface. Language is *not* detected here —
the system prompt instructs the model to reply in whichever language the farmer
used, so English in → English out, Kannada in → Kannada out.
"""
import logging

from openai import OpenAI, OpenAIError

from backend.ai.base import LLMProvider
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

# Bilingual so the farmer understands regardless of the language they asked in.
_FRIENDLY_ERROR = (
    "Sorry, the assistant is temporarily unavailable — please try again shortly. "
    "/ ಕ್ಷಮಿಸಿ, ಸಹಾಯಕ ತಾತ್ಕಾಲಿಕವಾಗಿ ಲಭ್ಯವಿಲ್ಲ — ದಯವಿಟ್ಟು ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ."
)


class GroqLLMProvider(LLMProvider):
    def __init__(self) -> None:
        s = get_settings()
        self._model = s.groq_model
        # The SDK requires a non-empty key to construct; a missing/invalid key
        # surfaces as a caught API error at call time rather than crashing boot.
        self._client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=s.groq_api_key or "not-set",
        )

    def answer(self, question: str, context: str, language: str) -> str:
        # `language` is ignored on purpose — the model matches the user's language.
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "system", "content": f"Current field context:\n{context}"},
                    {"role": "user", "content": question},
                ],
            )
            return resp.choices[0].message.content or _FRIENDLY_ERROR
        except OpenAIError:
            logger.exception("Groq request failed (model=%s)", self._model)
            return _FRIENDLY_ERROR
        except Exception:  # network / unexpected — never crash the backend
            logger.exception("Unexpected error calling Groq")
            return _FRIENDLY_ERROR
