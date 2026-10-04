"""Small, single-purpose Groq calls used around the answering model: rewriting a
farmer's question into an English search query, and checking an answer against
its context. Independent of LLM_PROVIDER (these always use Groq when a key is
set). Every function raises GroqUnavailable on any failure, so callers can fall
back instead of failing the request.
"""
import json
import logging

from openai import OpenAI

from backend.config import get_settings

logger = logging.getLogger("gage.ai.groq_client")


class GroqUnavailable(RuntimeError):
    """No key, timeout, network/API error, or an unusable response."""


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    s = get_settings()
    if not s.groq_api_key:
        raise GroqUnavailable("GROQ_API_KEY is not set")
    if _client is None:
        # No SDK retries: these are optional helpers with their own fallbacks,
        # and a retry would only add latency to the farmer's answer.
        _client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=s.groq_api_key,
                         max_retries=0)
    return _client


def chat(system: str, user: str, *, timeout: float, max_tokens: int,
         json_mode: bool = False) -> str:
    """One short completion. Raises GroqUnavailable on any failure."""
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    try:
        resp = _get_client().chat.completions.create(
            model=get_settings().groq_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0, max_completion_tokens=max_tokens, timeout=timeout,
            reasoning_effort="low",  # short helper tasks; keeps added latency down
            **kwargs,
        )
    except GroqUnavailable:
        raise
    except Exception as exc:
        raise GroqUnavailable(f"{type(exc).__name__}: {str(exc)[:160]}") from exc
    text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
    if not text:
        raise GroqUnavailable("empty response")
    return text


_REWRITE_SYSTEM = (
    "You turn a sugarcane farmer's question into a short English search query for "
    "an agricultural knowledge base. The question may be in English, Kannada script, "
    "or Kannada written in Latin letters (Kanglish); words like anna, sir, nodi, heli, "
    "madi, yaake, yavaga, eshtu are conversational Kannada, not crop terms. Keep "
    "domain terms (crop stage, pest, disease, nutrient, organisation names such as "
    "IISR or ICAR, units). Reply with only the query, at most 15 words, no quotes."
)


def rewrite_query(question: str) -> str:
    """Clean English search query for `question`. Raises GroqUnavailable."""
    q = chat(_REWRITE_SYSTEM, question, timeout=get_settings().groq_helper_timeout_s,
             max_tokens=400).splitlines()[0].strip().strip('"')
    if not q:
        raise GroqUnavailable("empty rewrite")
    return q


def chat_json(system: str, user: str, *, timeout: float, max_tokens: int) -> dict:
    """A completion that must be a JSON object. Raises GroqUnavailable."""
    text = chat(system, user, timeout=timeout, max_tokens=max_tokens, json_mode=True)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GroqUnavailable(f"invalid JSON: {text[:120]}") from exc
    if not isinstance(data, dict):
        raise GroqUnavailable("JSON is not an object")
    return data
