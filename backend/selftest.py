"""Smoke test for Gage's core logic. Run: python -m backend.selftest

Covers the pieces with real branching, no server needed:
- OpenCV image analysis and language detection/routing
- password hashing + JWT round-trip
- Farm Context Engine (grounding + tenant isolation) + trend detection
- structured prompt builder + grounding rules
- AI orchestrator + conversation memory
- rule-based health score
- observation merge (image + sensors), alert rules, offline detection
"""
import json
from datetime import datetime, timedelta

import cv2
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.ai import knowledge, prompt_builder
from backend.ai.mock import MockLLMProvider, MockSpeechProvider, MockVisionProvider
from backend.ai.orchestrator import AIOrchestrator
from backend.ai.service import detect_language, synthesize, transcribe
from backend.core.security import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_password,
    verify_password,
)
from backend.database import Base
from backend.dataset.exporter import Exporter
from backend.dataset.models import EXPORTED, VALIDATED, DatasetEntry
from backend.dataset.repository import DatasetFilters, DatasetRepository
from backend.dataset.service import DatasetService
from backend.models import (
    Alert,
    Conversation,
    Farm,
    Farmer,
    Node,
    NodeHealth,
    Observation,
)
from backend.services import alerts, farm_context, health_score, observation_service


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


def _obs(fid, nid, oid, ts, **kw):
    return Observation(id=oid, farm_id=fid, node_id=nid, timestamp=ts, **kw)


def test_context_engine_and_prompt() -> None:
    db = _memory_session()
    farmer = Farmer(phone="1", password_hash="x", name="A", language="en")
    db.add(farmer)
    db.flush()
    a = Farm(farmer_id=farmer.id, name="Farm A", crop_type="sugarcane", village="Mandya")
    b = Farm(farmer_id=farmer.id, name="Farm B")
    db.add_all([a, b])
    db.flush()
    db.add_all([
        Node(id="na", farm_id=a.id, api_key=generate_api_key()),
        Node(id="nb", farm_id=b.id, api_key=generate_api_key()),
    ])
    db.flush()
    t0 = datetime(2026, 7, 24, 8, 0)
    t1 = datetime(2026, 7, 25, 8, 0)
    db.add(_obs(a.id, "na", "o0", t0, temperature=28.0, humidity=60.0, soil_moisture=54.0,
                vision_summary="Healthy green foliage."))
    db.add(_obs(a.id, "na", "o1", t1, temperature=29.0, humidity=88.0, soil_moisture=42.0,
                vision_summary="Slight yellowing on some leaves."))
    db.add(Alert(farm_id=a.id, node_id="na", type="humidity_high", severity="warning",
                 message="High humidity 88% (disease risk)", value=88.0))
    db.commit()

    ctx = farm_context.build(db, a)
    # Context loads the right things, newest first.
    assert ctx.latest.id == "o1" and len(ctx.recent) == 2
    assert ctx.crop_type == "sugarcane" and ctx.location == "Mandya"
    assert len(ctx.active_alerts) == 1

    # Trend detection: soil moisture dropped 54 -> 42 (down 12), humidity up 60 -> 88.
    trends = {t.metric: t for t in ctx.trends}
    assert trends["soil_moisture"].delta == -12.0 and trends["soil_moisture"].direction == "down"
    assert trends["humidity"].direction == "up"

    # Prompt builder: structured sections + grounded facts + trend + alert + rules.
    docs = knowledge.retrieve("irrigation and humidity", "", k=3)
    prompt = prompt_builder.build(ctx, docs, "How is my field?")
    for section in ("# FARM", "# CURRENT OBSERVATION", "# SENSOR READINGS",
                    "# RECENT HISTORY", "# ACTIVE ALERTS", "# AGRICULTURAL KNOWLEDGE",
                    "# USER QUESTION"):
        assert section in prompt, f"missing section {section}"
    assert "Observed" in prompt and "Recommendation" in prompt   # grounding rules present
    assert "42.0" in prompt and "88.0" in prompt                 # grounded sensor facts
    assert "decreased by 12.0" in prompt                         # trend surfaced
    assert "High humidity 88%" in prompt                         # alert surfaced
    assert "sugarcane" in prompt.lower()

    # Tenant isolation: Farm B (no data) must not leak Farm A's numbers.
    ctx_b = farm_context.build(db, b)
    prompt_b = prompt_builder.build(ctx_b, [], "How is my field?")
    assert "No observation recorded yet" in prompt_b
    assert "42.0" not in prompt_b


def test_knowledge_retrieval() -> None:
    # "irrigate?" must match the "irrigation" doc despite the word/punctuation gap.
    hits = knowledge.retrieve("How is my crop and should I irrigate?", "", k=2)
    assert hits and any("irrigation" in d.title.lower() for d in hits)
    assert knowledge.retrieve("xyzzy unrelated gibberish", "", k=3) == []  # never guess


def test_orchestrator_and_memory() -> None:
    db = _memory_session()
    farm, node = _farm_with_node(db)
    db.add(_obs(farm.id, node.id, "o1", datetime(2026, 7, 25, 8, 0),
               temperature=29.0, humidity=60.0, soil_moisture=42.0,
               vision_summary="Healthy green foliage."))
    db.commit()

    ans1, lang1 = AIOrchestrator.answer(db, farm, "How is my crop?")
    assert ans1 and lang1 == "en"
    assert db.query(Conversation).count() == 1  # turn persisted (memory)

    # Second turn: prior conversation is in context (memory works).
    AIOrchestrator.answer(db, farm, "What about irrigation?")
    assert db.query(Conversation).count() == 2
    ctx = farm_context.build(db, farm)
    assert len(ctx.conversation) == 2 and ctx.conversation[0].question == "How is my crop?"


def test_health_score() -> None:
    db = _memory_session()
    farm, node = _farm_with_node(db)

    # Healthy snapshot -> high score.
    db.add(_obs(farm.id, node.id, "h1", datetime(2026, 7, 25, 8, 0),
               temperature=28.0, humidity=60.0, soil_moisture=45.0,
               vision_summary="Healthy green foliage dominates the frame."))
    db.commit()
    good = health_score.compute(farm_context.build(db, farm))
    assert good.score >= 80 and good.status == "Healthy"

    # Stressed snapshot: dry soil + high humidity + vision anomaly + alert -> low score.
    db.add(_obs(farm.id, node.id, "h2", datetime(2026, 7, 25, 9, 0),
               temperature=42.0, humidity=90.0, soil_moisture=12.0,
               vision_summary="Noticeable yellowing, possible disease."))
    db.add(Alert(farm_id=farm.id, node_id=node.id, type="soil_low",
                 severity="warning", message="Low soil moisture", value=12.0))
    db.commit()
    bad = health_score.compute(farm_context.build(db, farm))
    assert bad.score < good.score and bad.status in ("Watch", "Critical")
    assert any("soil moisture" in r.lower() for r in bad.reasons)


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


def test_speech_provider() -> None:
    sp = MockSpeechProvider()
    # STT: mock decodes the payload as text and detects language.
    text, lang = sp.transcribe("How is my crop?".encode())
    assert text == "How is my crop?" and lang == "en"
    _, kn = sp.transcribe("ಈ ಗಿಡ ಹೇಗಿದೆ?".encode())
    assert kn == "kn"
    # non-text audio -> mock falls back to a default question, never crashes.
    txt2, _ = sp.transcribe(b"\x00\x01\x02not-text")
    assert txt2

    # TTS returns a real, playable WAV.
    wav = sp.synthesize("Continue monitoring the field.", "en")
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"


def test_voice_loop_grounded() -> None:
    """speech -> orchestrator -> speech, grounded in the farm's own data."""
    db = _memory_session()
    farm, node = _farm_with_node(db)
    db.add(_obs(farm.id, node.id, "v1", datetime(2026, 7, 25, 8, 0),
               temperature=29.0, humidity=60.0, soil_moisture=19.0,
               vision_summary="Healthy green foliage."))
    db.commit()

    transcript, _lang = transcribe("Should I irrigate my field?".encode())
    answer, language = AIOrchestrator.answer(db, farm, transcript)
    assert "19.0" in answer          # grounded in this farm's soil moisture
    audio = synthesize(answer, language)
    assert audio[:4] == b"RIFF"      # spoken answer is valid audio
    assert db.query(Conversation).count() == 1  # voice turn saved to memory


def _complete_obs(fid, nid, oid, **kw):
    from datetime import datetime as _dt
    base = dict(image_path=f"{oid}.jpg", gps_lat=12.9, gps_long=77.5,
                temperature=28.0, humidity=60.0, soil_moisture=45.0,
                vision_summary="Healthy green foliage dominates the frame.",
                timestamp=_dt.utcnow())
    base.update(kw)
    return Observation(id=oid, farm_id=fid, node_id=nid, **base)


def test_dataset_generation_and_quality() -> None:
    db = _memory_session()
    farm, node = _farm_with_node(db)

    # Complete observation -> high quality, VALIDATED, healthy label.
    db.add(_complete_obs(farm.id, node.id, "c1"))
    db.commit()
    e1 = DatasetService.build_from_observation(db, db.get(Observation, "c1"))
    assert e1.quality_score == 100 and e1.status == VALIDATED
    assert e1.crop_type == "sugarcane"
    assert "healthy" in e1.labels

    # Idempotent: rebuilding the same observation does not duplicate.
    DatasetService.build_from_observation(db, db.get(Observation, "c1"))
    assert db.query(DatasetEntry).count() == 1

    # Sparse observation (no image, no GPS, one sensor) -> lower quality, reasons.
    db.add(_obs(farm.id, node.id, "c2", datetime(2026, 7, 25, 8, 0),
               soil_moisture=15.0, vision_summary=None))
    db.commit()
    e2 = DatasetService.build_from_observation(db, db.get(Observation, "c2"))
    assert e2.quality_score < e1.quality_score
    assert "image missing" in e2.quality_reason and "missing GPS" in e2.quality_reason


def test_label_generation() -> None:
    db = _memory_session()
    farm, node = _farm_with_node(db)
    db.add(_obs(farm.id, node.id, "l1", datetime(2026, 7, 25, 8, 0),
               humidity=90.0, soil_moisture=12.0,
               vision_summary="Noticeable yellowing, possible pest damage."))
    db.commit()
    e = DatasetService.build_from_observation(db, db.get(Observation, "l1"))
    for label in ("dry_soil", "water_stress", "high_humidity", "possible_disease"):
        assert label in e.labels, f"expected {label} in {e.labels}"

    # Negation: "No yellowing ... No pest damage" must NOT yield possible_disease.
    db.add(_obs(farm.id, node.id, "l2", datetime(2026, 7, 25, 9, 0),
               temperature=28.0, humidity=60.0, soil_moisture=45.0,
               vision_summary="Healthy green foliage dominates the frame. "
                              "No significant yellowing observed. No obvious pest damage detected."))
    db.commit()
    e2 = DatasetService.build_from_observation(db, db.get(Observation, "l2"))
    assert "healthy" in e2.labels and "possible_disease" not in e2.labels, e2.labels


def test_export_filtering_and_versioning() -> None:
    import os
    db = _memory_session()
    farm, node = _farm_with_node(db)
    db.add(_complete_obs(farm.id, node.id, "x1"))  # quality 100
    db.add(_obs(farm.id, node.id, "x2", datetime(2026, 7, 25, 8, 0),
               soil_moisture=15.0))               # low quality (no image/gps/vision)
    db.commit()
    for oid in ("x1", "x2"):
        DatasetService.build_from_observation(db, db.get(Observation, oid))

    farm_ids = [farm.id]
    # Filter: only high-quality entries export.
    exp = Exporter.export(db, farm_ids, DatasetFilters(min_quality=80), "jsonl")
    try:
        assert exp.record_count == 1 and exp.dataset_version.startswith("v")
        assert len(exp.checksum) == 64
        contents = open(exp.path, encoding="utf-8").read().strip().splitlines()
        assert len(contents) == 1 and json.loads(contents[0])["observation_id"] == "x1"
        assert db.query(DatasetEntry).filter(DatasetEntry.observation_id == "x1").one().status == EXPORTED
    finally:
        os.remove(exp.path)

    # CSV export of everything.
    exp2 = Exporter.export(db, farm_ids, DatasetFilters(), "csv")
    try:
        assert exp2.record_count == 2
        assert open(exp2.path, encoding="utf-8").readline().startswith("dataset_id,")
    finally:
        os.remove(exp2.path)


def test_dataset_stats_and_conversation_linking() -> None:
    db = _memory_session()
    farm, node = _farm_with_node(db)
    db.add(_obs(farm.id, node.id, "s1", datetime(2026, 7, 25, 8, 0),
               temperature=28.0, humidity=60.0, soil_moisture=45.0,
               vision_summary="Healthy green foliage."))
    db.commit()
    DatasetService.build_from_observation(db, db.get(Observation, "s1"))

    stats = DatasetRepository.stats(db, [farm.id])
    assert stats["dataset_entries"] == 1
    assert stats["crop_distribution"].get("sugarcane") == 1
    assert "daily_rate" in stats

    # Conversation grounded in observation s1 (asked after it) -> linked.
    db.add(Conversation(farm_id=farm.id, farmer_id=farm.farmer_id,
                        question="Why are my leaves yellow?", answer="...",
                        language="en", timestamp=datetime(2026, 7, 25, 9, 0)))
    db.commit()
    linked = DatasetService.link_recent_conversations(db, farm.id)
    assert linked == 1
    entry = DatasetRepository.get_by_observation(db, "s1")
    convo = db.query(Conversation).one()
    assert entry.conversation_reference == convo.id


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
    test_context_engine_and_prompt()
    test_knowledge_retrieval()
    test_orchestrator_and_memory()
    test_health_score()
    test_speech_provider()
    test_voice_loop_grounded()
    test_dataset_generation_and_quality()
    test_label_generation()
    test_export_filtering_and_versioning()
    test_dataset_stats_and_conversation_linking()
    test_merge_and_alerts()
    test_offline_detection()
    print("OK — all self-checks passed")
