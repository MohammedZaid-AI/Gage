"""Turn a farmer's question into English for retrieval, via Sarvam's text APIs.

The knowledge base is English. A multilingual embedder alone did not match
Kannada-script or romanized-Kannada questions to the right documents (measured:
both retrieved unrelated sections, and an off-topic Kannada question outscored
on-topic ones), so non-English questions are translated before retrieval:

- Kannada script         -> /translate (kn -> en)
- romanized Kannada      -> /transliterate (Latin -> Kannada script) -> /translate

Only retrieval uses the translation; the model still sees the farmer's own words.
"""
import logging

import httpx

from backend.config import get_settings

logger = logging.getLogger("gage.query_translation")

_BASE = "https://api.sarvam.ai"
_TIMEOUT = 15.0


class TranslationUnavailable(RuntimeError):
    """Sarvam is not configured or the call failed."""


def _post(path: str, body: dict) -> dict:
    key = get_settings().sarvam_api_key
    if not key:
        raise TranslationUnavailable("SARVAM_API_KEY is not set")
    try:
        resp = httpx.post(f"{_BASE}{path}", json=body, timeout=_TIMEOUT,
                          headers={"api-subscription-key": key})
    except httpx.HTTPError as exc:
        raise TranslationUnavailable(f"Sarvam {path} unreachable: {exc}") from exc
    if resp.status_code >= 400:
        raise TranslationUnavailable(f"Sarvam {path} -> HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def kannada_to_english(text: str) -> str:
    """Kannada-script (or mixed) text -> English."""
    out = _post("/translate", {
        "input": text, "source_language_code": "auto",
        "target_language_code": "en-IN", "model": "mayura:v1",
    }).get("translated_text", "")
    if not out.strip():
        raise TranslationUnavailable("Sarvam /translate returned no text")
    return out


def romanized_kannada_to_english(text: str) -> str:
    """Kannada written in Latin letters -> Kannada script -> English."""
    script = _post("/transliterate", {
        "input": text, "source_language_code": "en-IN", "target_language_code": "kn-IN",
    }).get("transliterated_text", "")
    if not script.strip():
        raise TranslationUnavailable("Sarvam /transliterate returned no text")
    return kannada_to_english(script)
