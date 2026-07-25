"""Smoke test for Gage's core logic. Run: python -m backend.selftest

Covers the pieces with real branching, no server needed:
- OpenCV image analysis and language detection/routing
- password hashing + JWT round-trip
- farm-scoped context assembly (grounding + tenant isolation)
- observation merge (image + sensors), alert rules, offline detection
"""
from datetime import datetime, timedelta

import cv2
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.ai.mock import MockLLMProvider, MockVisionProvider
from backend.ai.service import _build_context, detect_language
from backend.core.security import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_password,
    verify_password,
)
from backend.database import Base
from backend.models import Alert, Farm, Farmer, Node, NodeHealth, Observation
from backend.services import alerts, observation_service


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
    db.add_all([
        Node(id="na", farm_id=a.id, api_key=generate_api_key()),
        Node(id="nb", farm_id=b.id, api_key=generate_api_key()),
    ])
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


def _farm_with_node(db):
    farmer = Farmer(phone="m", password_hash="x", name="M", language="en")
    db.add(farmer)
    db.flush()
    farm = Farm(farmer_id=farmer.id, name="Farm M")
    db.add(farm)
    db.flush()
    node = Node(id="node-m", farm_id=farm.id, api_key=generate_api_key())
    db.add(node)
    db.commit()
    return farm, node


def test_merge_and_alerts() -> None:
    db = _memory_session()
    farm, node = _farm_with_node(db)

    # ESP32 pushes sensors first: dry soil -> a soil_low alert; observation is sensor-only.
    obs1, reading, raised = observation_service.ingest_sensors(
        db, node, temperature=30.0, humidity=60.0, soil_moisture=10.0,
        battery=95.0, timestamp=None,
    )
    assert reading.observation_id == obs1.id
    assert obs1.image_path is None and obs1.ai_summary is None  # not complete yet
    assert any(a.type == "soil_low" for a in raised)

    # Phone pushes an image within the window -> merges into the SAME observation,
    # runs vision, and (now complete) generates the AI summary.
    green = np.zeros((60, 60, 3), np.uint8)
    green[:] = (40, 180, 40)
    obs2 = observation_service.ingest_image(
        db, node, _encode(green), "f.jpg", 12.9, 77.5, None,
    )
    assert obs2.id == obs1.id, "image must merge into the open sensor observation"
    assert obs2.image_path and obs2.vision_summary and obs2.ai_summary
    assert db.query(Observation).count() == 1  # one merged observation, not two

    # De-dup: a second dry reading must not raise a second open soil_low alert.
    observation_service.ingest_sensors(db, node, None, None, 8.0, 95.0, None)
    assert db.query(Alert).filter(Alert.type == "soil_low").count() == 1


def test_offline_detection() -> None:
    db = _memory_session()
    farm, node = _farm_with_node(db)
    db.add(NodeHealth(
        node_id=node.id, status="online",
        last_seen=datetime.utcnow() - timedelta(minutes=10),  # stale
    ))
    db.commit()

    raised = alerts.evaluate_offline(db)
    db.commit()
    assert any(a.type == "node_offline" for a in raised)
    assert db.get(NodeHealth, node.id).status == "offline"

    # Fresh heartbeat -> recovers, no duplicate alert on re-eval.
    db.get(NodeHealth, node.id).last_seen = datetime.utcnow()
    db.commit()
    assert alerts.evaluate_offline(db) == []
    assert db.get(NodeHealth, node.id).status == "online"


if __name__ == "__main__":
    test_vision_reads_the_image()
    test_language_detection_and_routing()
    test_password_and_token()
    test_context_is_farm_scoped()
    test_merge_and_alerts()
    test_offline_detection()
    print("OK — all self-checks passed")
