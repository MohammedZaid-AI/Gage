"""Sarvam AI speech provider: Kannada/English speech-to-text and text-to-speech.

Implements the shared `SpeechProvider` interface. Selected when SPEECH_PROVIDER=sarvam.
The mock provider is used until this is keyed, so the voice loop is testable offline.

NOTE: endpoint paths, field names, and model ids follow Sarvam's documented API
(api.sarvam.ai, api-subscription-key auth). Confirm against the current Sarvam
docs for your account before production — this module is the only place they live.
"""
import base64
import logging

import httpx

from backend.ai.base import SpeechProvider
from backend.config import get_settings

logger = logging.getLogger("gage.ai.sarvam")

_BASE = "https://api.sarvam.ai"
_TIMEOUT = 30.0
_TTS_MAX_CHARS = 480  # Sarvam caps TTS input length; keep well under it.


def _lang_code(language: str | None) -> str:
    """Map our short codes to Sarvam's BCP-47 codes; 'unknown' lets Sarvam detect."""
    return {"kn": "kn-IN", "en": "en-IN"}.get((language or "").lower(), "unknown")


def _short(code: str) -> str:
    return "kn" if code.startswith("kn") else "en"


class SarvamSpeechProvider(SpeechProvider):
    def __init__(self) -> None:
        s = get_settings()
        self._key = s.sarvam_api_key
        self._stt_model = s.sarvam_stt_model
        self._tts_model = s.sarvam_tts_model
        self._speaker = s.sarvam_speaker
        if not self._key:
            logger.warning("SARVAM_API_KEY is empty; Sarvam calls will fail until set")

    @property
    def _headers(self) -> dict[str, str]:
        return {"api-subscription-key": self._key}

    def _check(self, resp: httpx.Response, what: str) -> None:
        """Surface Sarvam's actual error body (status + message) before raising."""
        if resp.status_code >= 400:
            logger.error("Sarvam %s -> HTTP %s: %s", what, resp.status_code, resp.text[:400])
            resp.raise_for_status()

    def transcribe(self, audio: bytes, language: str | None = None) -> tuple[str, str]:
        # Browsers record webm/opus; Sarvam expects wav/mp3. We pass it through with
        # the reported type; if STT rejects the format the error body will say so.
        resp = httpx.post(
            f"{_BASE}/speech-to-text",
            headers=self._headers,
            data={"model": self._stt_model, "language_code": _lang_code(language)},
            files={"file": ("audio.webm", audio, "audio/webm")},
            timeout=_TIMEOUT,
        )
        self._check(resp, "speech-to-text")
        body = resp.json()
        transcript = body.get("transcript", "")
        code = body.get("language_code") or _lang_code(language)
        return transcript, _short(code)

    def synthesize(self, text: str, language: str) -> bytes:
        resp = httpx.post(
            f"{_BASE}/text-to-speech",
            headers={**self._headers, "Content-Type": "application/json"},
            json={
                "inputs": [text[:_TTS_MAX_CHARS]],   # Sarvam expects a list of texts
                "target_language_code": _lang_code(language),
                "speaker": self._speaker,
                "model": self._tts_model,
            },
            timeout=_TIMEOUT,
        )
        self._check(resp, "text-to-speech")
        audios = resp.json().get("audios") or []
        if not audios:
            raise RuntimeError("Sarvam TTS returned no audio")
        return base64.b64decode(audios[0])
