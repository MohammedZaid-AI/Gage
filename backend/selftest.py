"""Smoke test for Gage's core logic. Run: python -m backend.selftest

Checks the two pieces with real branching: OpenCV image analysis and language
detection/routing. No server or DB needed.
"""
import cv2
import numpy as np

from backend.ai.mock import MockLLMProvider, MockVisionProvider
from backend.ai.service import detect_language


def _encode(bgr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", bgr)
    assert ok
    return buf.tobytes()


def test_vision_reads_the_image() -> None:
    vision = MockVisionProvider()

    green = np.zeros((80, 80, 3), np.uint8)
    green[:] = (40, 180, 40)  # BGR green
    assert "green foliage" in vision.describe(_encode(green)).lower()

    yellow = np.zeros((80, 80, 3), np.uint8)
    yellow[:] = (30, 200, 220)  # BGR yellow
    assert "yellow" in vision.describe(_encode(yellow)).lower()

    assert "could not be decoded" in vision.describe(b"not an image")


def test_language_detection_and_routing() -> None:
    assert detect_language("How is this plant?") == "en"
    assert detect_language("ಈ ಗಿಡ ಹೇಗಿದೆ?") == "kn"
    assert detect_language("mixed ಗಿಡ text") == "kn"

    llm = MockLLMProvider()
    kn = llm.answer("ಈ ಗಿಡ ಹೇಗಿದೆ?", "ctx", "kn")
    assert any("಄" <= c <= "೿" for c in kn), "Kannada question must get a Kannada answer"
    en = llm.answer("how is it?", "ctx", "en")
    assert "plant" in en.lower()


if __name__ == "__main__":
    test_vision_reads_the_image()
    test_language_detection_and_routing()
    print("OK — all self-checks passed")
