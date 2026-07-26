"""Offline mock providers. Real image analysis via OpenCV, templated LLM answers.

These run with no API keys and make the full demo work. The vision mock does
genuine pixel analysis so descriptions vary with the actual image.
"""
import io
import logging
import wave

import cv2
import numpy as np

from backend.ai.base import LLMProvider, SpeechProvider, VisionProvider

logger = logging.getLogger("gage.ai.mock")


class MockVisionProvider(VisionProvider):
    def describe(self, image_bytes: bytes) -> str:
        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return "Image could not be decoded; no visual analysis available."

        h, w = img.shape[:2]
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        total = float(h * w)

        # HSV masks: green foliage, yellowing, dark/brown regions.
        green = cv2.inRange(hsv, (35, 40, 40), (85, 255, 255)).sum() / 255 / total
        yellow = cv2.inRange(hsv, (20, 40, 40), (34, 255, 255)).sum() / 255 / total
        brightness = float(hsv[:, :, 2].mean()) / 255

        parts: list[str] = []
        if green > 0.35:
            parts.append("Healthy green foliage dominates the frame.")
        elif green > 0.12:
            parts.append("Moderate green cover; canopy is thinner than ideal.")
        else:
            parts.append("Little green foliage detected; sparse or stressed vegetation.")

        if yellow > 0.15:
            parts.append("Noticeable yellowing, possibly on lower leaves.")
        elif yellow > 0.05:
            parts.append("Slight yellowing visible on some leaves.")
        else:
            parts.append("No significant yellowing observed.")

        parts.append("No obvious pest damage detected." if brightness > 0.25
                     else "Low light; inspect again in better lighting.")
        return " ".join(parts)


# Templated, context-grounded answers. A real LLM replaces this transparently.
_KANNADA_HINT = (
    "ಗಿಡದ ಇತ್ತೀಚಿನ ಪರಿಶೀಲನೆಯ ಆಧಾರದ ಮೇಲೆ ಉತ್ತರ:"
)


class MockLLMProvider(LLMProvider):
    def answer(self, question: str, context: str, language: str) -> str:
        if language == "kn":
            return (
                f"{_KANNADA_HINT}\n{context}\n\n"
                "ಗಿಡ ಸಾಮಾನ್ಯ ಸ್ಥಿತಿಯಲ್ಲಿದೆ. ಮಣ್ಣಿನ ತೇವಾಂಶ ಮತ್ತು "
                "ಎಲೆಗಳ ಬಣ್ಣವನ್ನು ಗಮನಿಸುತ್ತಿರಿ."
            )
        return (
            "Based on the latest field data:\n"
            f"{context}\n\n"
            "The plant looks stable overall. Keep an eye on soil moisture and "
            "leaf colour, and re-inspect if yellowing spreads."
        )


def _silent_wav(seconds: float = 1.0, rate: int = 8000) -> bytes:
    """A valid mono 16-bit WAV of silence — a real, playable audio file."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


class MockSpeechProvider(SpeechProvider):
    """Offline stand-in for Sarvam. STT decodes the payload as UTF-8 text so the
    whole voice loop is testable without a speech model; TTS returns a short
    silent WAV. Real speech is a config swap to the Sarvam provider."""

    def transcribe(self, audio: bytes, language: str | None = None) -> tuple[str, str]:
        from backend.ai.service import detect_language  # lazy: avoid import cycle

        try:
            text = audio.decode("utf-8").strip()
        except UnicodeDecodeError:
            text = ""  # real (non-text) audio bytes -> mock can't transcribe
        text = text or "How is my field?"
        return text, language or detect_language(text)

    def synthesize(self, text: str, language: str) -> bytes:
        return _silent_wav(seconds=min(4.0, max(1.0, len(text) / 25)))
