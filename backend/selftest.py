"""Smoke test for Gage's core logic. Run: python -m backend.selftest

Covers the pieces with real branching, no server needed:
- OpenCV image analysis and language detection/routing
- password hashing + JWT round-trip
- farm-scoped context assembly (grounding + tenant isolation)
"""
import cv2
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.ai.mock import MockLLMProvider, MockVisionProvider
from backend.ai.service import _build_context, detect_language
from backend.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from backend.database import Base
from backend.models import Farm, Farmer, Node, Observation


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


def test_password_and_token() -> None:
    h = hash_password("s3cret")
    assert verify_password("s3cret", h)
    assert not verify_password("wrong", h)

    token = create_access_token(42)
    assert decode_access_token(token) == 42
    assert decode_access_token("garbage") is None


def _memory_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_context_is_farm_scoped() -> None:
    db = _memory_session()
    farmer = Farmer(phone="1", password_hash="x", name="A")
    db.add(farmer)
    db.flush()
    a = Farm(farmer_id=farmer.id, name="Farm A", village="Mandya")
    b = Farm(farmer_id=farmer.id, name="Farm B")
    db.add_all([a, b])
    db.flush()
    db.add_all([Node(id="na", farm_id=a.id), Node(id="nb", farm_id=b.id)])
    db.flush()
    db.add(Observation(
        id="o1", farm_id=a.id, node_id="na",
        temperature=27.5, humidity=60.0, soil_moisture=41.0,
        vision_summary="Healthy green foliage dominates the frame.",
    ))
    db.commit()

    ctx = _build_context(db, a.id)
    assert "Farm A" in ctx and "Mandya" in ctx       # farm identity grounded
    assert "27.5" in ctx and "41.0" in ctx           # sensor readings grounded
    assert "Healthy green foliage" in ctx            # vision grounded

    other = _build_context(db, b.id)                 # Farm B has no observations
    assert "No observations recorded yet" in other
    assert "27.5" not in other                       # tenant isolation: no A data leaks


if __name__ == "__main__":
    test_vision_reads_the_image()
    test_language_detection_and_routing()
    test_password_and_token()
    test_context_is_farm_scoped()
    print("OK — all self-checks passed")
