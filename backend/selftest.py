"""Smoke test for Gage's core logic. Run: python -m backend.selftest

Covers the pieces with real branching, no server needed:
- language detection/routing
- password hashing + JWT round-trip
- Farm Context Engine (grounding + tenant isolation) + trend detection
- structured prompt builder + grounding rules
- AI orchestrator + conversation memory
- rule-based health score
- observation merge (image + sensors), alert rules, offline detection
"""
import json
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.ai import knowledge, prompt_builder
from backend.ai.mock import MockLLMProvider, MockSpeechProvider
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
    db.add(_obs(a.id, "na", "o0", t0, temperature=28.0, humidity=60.0, soil_moisture=54.0))
    db.add(_obs(a.id, "na", "o1", t1, temperature=29.0, humidity=88.0, soil_moisture=42.0))
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
    docs = knowledge.retrieve("How much water and how often should I irrigate?", k=3).docs
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


def test_crop_doctor_prompt_and_intents() -> None:
    di = prompt_builder.detect_intent
    assert di("Should I irrigate my field?") == "irrigation"
    assert di("Is this red rot disease?") == "disease"
    assert di("How much urea fertilizer to apply?") == "fertilizer"
    assert di("Any borer pest attack?") == "pest"
    assert di("How is my crop growth this week?") == "growth"
    assert di("Hello Gage") == "general"

    db = _memory_session()
    farm, node = _farm_with_node(db)
    # Two observations 3 days apart; sensors show stress.
    db.add(_obs(farm.id, node.id, "d0", datetime(2026, 7, 22, 8, 0),
               temperature=28.0, humidity=60.0, soil_moisture=50.0))
    db.add(_obs(farm.id, node.id, "d1", datetime(2026, 7, 25, 8, 0),
               temperature=29.0, humidity=90.0, soil_moisture=15.0))
    db.add(Alert(farm_id=farm.id, node_id=node.id, type="soil_low", severity="warning",
                 message="Low soil moisture 15% (water stress)", value=15.0))
    db.commit()

    prompt = prompt_builder.build(farm_context.build(db, farm), [], "Should I irrigate?")
    # Response contract: sections + insufficient-evidence rule + expert-help step.
    for token in ("Observation:", "Analysis:", "Confidence:", "When to seek expert help",
                  "I don't have enough evidence from the latest observation."):
        assert token in prompt, f"missing {token!r}"
    assert "Observed Facts" in prompt and "Inference" in prompt  # facts vs inference
    assert "# FOCUS FOR THIS QUESTION (irrigation)" in prompt    # intent template
    assert "Address these FIRST" in prompt                       # alert prioritization
    assert "VISION" not in prompt                                # no image evidence section
    assert "compared to 3 days ago" in prompt                    # multi-observation comparison


def _offline_translation():
    """Make query translation unavailable, so these checks need no network."""
    from backend.ai import query_translation as qt

    def unavailable(_text):
        raise qt.TranslationUnavailable("offline selftest")
    qt.kannada_to_english = unavailable
    qt.romanized_kannada_to_english = unavailable


def test_knowledge_retrieval() -> None:
    _offline_translation()
    # Real retrieval over knowledge_base/: an English question lands on the right
    # document by meaning (no shared keyword needed).
    hits = knowledge.retrieve("How deep should each irrigation be for sugarcane?", k=3).docs
    assert hits and hits[0].source.startswith("irrigation/"), [h.source for h in hits]
    chl = knowledge.retrieve("Leaves turning yellow with green veins in my ratoon crop, "
                             "which nutrient is deficient?", k=3).docs
    assert any(h.source.startswith("nutrient_deficiency/") for h in chl), [h.source for h in chl]
    # Unrelated question -> nothing above the relevance floor (never guess).
    assert knowledge.retrieve("Who won the cricket world cup in 2011?", k=3).docs == []


def test_claim_check() -> None:
    from backend.ai import claim_check

    ctx = "Foliar spray of 2% FeSO4 with 0.5% MnSO4 and 2% urea, 2-3 times. Iron chlorosis."
    ok = claim_check.check("Spray 2% FeSO4 and 2% urea for iron chlorosis.", ctx)
    assert ok.unsupported == [] and ok.answer.startswith("Spray")
    bad = claim_check.check("This is calcium deficiency; apply 75 kg/ha in March.", ctx)
    assert set(bad.unsupported) == {"calcium", "75", "March"}, bad.unsupported
    assert bad.answer.startswith("Please double-check")      # caveat, not stated as fact
    # Invented people are flagged; a person named in the context is not.
    vksa = "VKSA was launched by Union Agriculture Minister Shri Shivraj Singh Chouhan."
    made_up = claim_check.check("Launched by Agriculture Minister Ramesh Kumar Gowda, "
                                "on advice from Dr. Raghupathy Srinivasan.", vksa)
    assert {"name: Ramesh Kumar Gowda", "name: Raghupathy Srinivasan"} <= set(made_up.unsupported)
    assert claim_check.check("It was launched by Shivraj Singh Chouhan, Union Minister.",
                             vksa).unsupported == []
    kn = claim_check.check("ಹೆಕ್ಟೇರ್‌ಗೆ ೭೫ kg ಕ್ಯಾಲ್ಸಿಯಂ ಹಾಕಿ.", ctx, "kn")
    assert {"75", "calcium"} <= set(kn.unsupported) and kn.answer.startswith("ದಯವಿಟ್ಟು")


def test_llm_failure_is_not_saved() -> None:
    """A failing model must raise, and nothing may be stored as an answer."""
    from backend.ai import service
    from backend.ai.base import LLMError, LLMProvider

    class Broken(LLMProvider):
        def answer(self, question, context, language):
            raise LLMError("model offline")

    db = _memory_session()
    farm, _node = _farm_with_node(db)
    real, service._llm = service._llm, Broken()
    try:
        try:
            AIOrchestrator.answer(db, farm, "Should I irrigate?")
            raise AssertionError("LLMError was swallowed")
        except LLMError:
            pass
        assert db.query(Conversation).count() == 0
    finally:
        service._llm = real


def test_compact_prompt_for_finetuned_model() -> None:
    from backend.ai.providers.sarvam_llm import SYSTEM_PROMPT, build_prompt

    db = _memory_session()
    farm, node = _farm_with_node(db)
    db.add(_obs(farm.id, node.id, "cp1", datetime(2026, 7, 25, 8, 0),
               temperature=29.0, humidity=60.0, soil_moisture=19.0))
    db.commit()
    docs = [knowledge.KnowledgeDoc("T", "Irrigate at 7-8 cm depth.", "irrigation/x.md")]
    ctx, farmer = prompt_builder.build_compact(docs, "Should I irrigate?")
    # Knowledge only, and the farmer's own words only: no sensor data at all.
    assert ctx == "Irrigate at 7-8 cm depth." and farmer == "Should I irrigate?"

    # End to end: what a compact-style model actually receives via the orchestrator
    # must not contain the farm's readings (19.0 / 29.0 / 60.0).
    from backend.ai import service
    from backend.ai.base import LLMProvider

    seen = {}

    class Capture(LLMProvider):
        prompt_style = "compact"

        def answer(self, question, context, language):
            seen.update(question=question, context=context)
            return "Irrigate at 7-8 cm."

    _offline_translation()
    real, service._llm = service._llm, Capture()
    try:
        AIOrchestrator.answer(db, farm, "How deep should each irrigation be for sugarcane?")
    finally:
        service._llm = real
    model_input = seen["question"] + seen["context"]
    assert not any(v in model_input for v in ("19.0", "29.0", "60.0")), model_input
    assert seen["question"] == "How deep should each irrigation be for sugarcane?"

    prompt = build_prompt(farmer, ctx)
    # Exactly the training template from Gage_Sarvam_Finetune_Colab.ipynb.
    assert prompt == (f"### System\n{SYSTEM_PROMPT}\n\n### Context\n{ctx}\n\n"
                      f"### Farmer\n{farmer}\n\n### Assistant\n")


def test_orchestrator_and_memory() -> None:
    db = _memory_session()
    farm, node = _farm_with_node(db)
    db.add(_obs(farm.id, node.id, "o1", datetime(2026, 7, 25, 8, 0),
               temperature=29.0, humidity=60.0, soil_moisture=42.0))
    db.commit()

    r1 = AIOrchestrator.answer(db, farm, "How is my crop?")
    assert r1.answer and r1.language == "en"
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
               temperature=28.0, humidity=60.0, soil_moisture=45.0))
    db.commit()
    good = health_score.compute(farm_context.build(db, farm))
    assert good.score >= 80 and good.status == "Healthy"

    # Stressed snapshot: dry soil + high humidity + heat + alert -> low score.
    db.add(_obs(farm.id, node.id, "h2", datetime(2026, 7, 25, 9, 0),
               temperature=42.0, humidity=90.0, soil_moisture=12.0))
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
    assert obs1.image_path is None and obs1.ai_summary is None  # summaries run later
    assert any(a.type == "soil_low" for a in raised)

    # Summary trigger: a new alert makes a summary due; it runs as a background
    # task with its own session, not inside the sensor request.
    assert observation_service.summary_due(db, obs1, raised)
    factory = sessionmaker(bind=db.get_bind())
    observation_service.generate_summary(obs1.id, session_factory=factory)
    db.expire_all()
    assert db.get(Observation, obs1.id).ai_summary
    # Right after a summary, an alert-free reading is NOT due (no per-reading AI).
    assert not observation_service.summary_due(db, db.get(Observation, obs1.id), [])

    # Phone pushes an image within the window -> merges into the SAME observation.
    # The bytes are stored, not decoded.
    obs2 = observation_service.ingest_image(
        db, node, b"\xff\xd8\xff stored-not-analysed", "f.jpg", 12.9, 77.5, None,
    )
    assert obs2.id == obs1.id, "image must merge into the open sensor observation"
    assert obs2.image_path
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
               temperature=29.0, humidity=60.0, soil_moisture=19.0))
    db.commit()

    transcript, _lang = transcribe("Should I irrigate my field?".encode())
    result = AIOrchestrator.answer(db, farm, transcript)
    answer, language = result.answer, result.language
    assert "19.0" in answer          # grounded in this farm's soil moisture
    audio = synthesize(answer, language)
    assert audio[:4] == b"RIFF"      # spoken answer is valid audio
    assert db.query(Conversation).count() == 1  # voice turn saved to memory


def _complete_obs(fid, nid, oid, **kw):
    from datetime import datetime as _dt
    base = dict(image_path=f"{oid}.jpg", gps_lat=12.9, gps_long=77.5,
                temperature=28.0, humidity=60.0, soil_moisture=45.0,
                timestamp=_dt.utcnow())
    base.update(kw)
    return Observation(id=oid, farm_id=fid, node_id=nid, **base)


def test_dataset_generation_and_quality() -> None:
    db = _memory_session()
    farm, node = _farm_with_node(db)

    # Complete observation -> high quality, VALIDATED, neutral label.
    db.add(_complete_obs(farm.id, node.id, "c1"))
    db.commit()
    e1 = DatasetService.build_from_observation(db, db.get(Observation, "c1"))
    assert e1.quality_score == 80 and e1.status == VALIDATED
    assert e1.quality_reason == "complete"
    assert e1.crop_type == "sugarcane"
    assert e1.labels == ["normal_growth"]

    # Idempotent: rebuilding the same observation does not duplicate.
    DatasetService.build_from_observation(db, db.get(Observation, "c1"))
    assert db.query(DatasetEntry).count() == 1

    # Sparse observation (no image, no GPS, one sensor) -> lower quality, reasons.
    db.add(_obs(farm.id, node.id, "c2", datetime(2026, 7, 25, 8, 0),
               soil_moisture=15.0))
    db.commit()
    e2 = DatasetService.build_from_observation(db, db.get(Observation, "c2"))
    assert e2.quality_score < e1.quality_score
    assert "image missing" in e2.quality_reason and "missing GPS" in e2.quality_reason


def test_label_generation() -> None:
    db = _memory_session()
    farm, node = _farm_with_node(db)
    db.add(_obs(farm.id, node.id, "l1", datetime(2026, 7, 25, 8, 0),
               humidity=90.0, soil_moisture=12.0))
    db.commit()
    e = DatasetService.build_from_observation(db, db.get(Observation, "l1"))
    for label in ("dry_soil", "water_stress", "high_humidity"):
        assert label in e.labels, f"expected {label} in {e.labels}"

    # In-range sensors and no alerts -> the neutral label only.
    db.add(_obs(farm.id, node.id, "l2", datetime(2026, 7, 25, 9, 0),
               temperature=28.0, humidity=60.0, soil_moisture=45.0))
    db.commit()
    e2 = DatasetService.build_from_observation(db, db.get(Observation, "l2"))
    assert e2.labels == ["normal_growth"], e2.labels


def test_export_filtering_and_versioning() -> None:
    import os
    db = _memory_session()
    farm, node = _farm_with_node(db)
    db.add(_complete_obs(farm.id, node.id, "x1"))  # quality 80
    db.add(_obs(farm.id, node.id, "x2", datetime(2026, 7, 25, 8, 0),
               soil_moisture=15.0))               # low quality (no image/gps)
    db.commit()
    for oid in ("x1", "x2"):
        DatasetService.build_from_observation(db, db.get(Observation, oid))

    farm_ids = [farm.id]
    # Filter: only high-quality entries export.
    exp = Exporter.export(db, farm.farmer_id, farm_ids, DatasetFilters(min_quality=80), "jsonl")
    try:
        assert exp.record_count == 1 and exp.dataset_version.startswith("v")
        assert len(exp.checksum) == 64
        contents = open(exp.path, encoding="utf-8").read().strip().splitlines()
        assert len(contents) == 1 and json.loads(contents[0])["observation_id"] == "x1"
        assert db.query(DatasetEntry).filter(DatasetEntry.observation_id == "x1").one().status == EXPORTED
    finally:
        os.remove(exp.path)

    # CSV export of everything.
    exp2 = Exporter.export(db, farm.farmer_id, farm_ids, DatasetFilters(), "csv")
    try:
        assert exp2.record_count == 2
        assert open(exp2.path, encoding="utf-8").readline().startswith("dataset_id,")
    finally:
        os.remove(exp2.path)


def test_dataset_stats_and_conversation_linking() -> None:
    db = _memory_session()
    farm, node = _farm_with_node(db)
    db.add(_obs(farm.id, node.id, "s1", datetime(2026, 7, 25, 8, 0),
               temperature=28.0, humidity=60.0, soil_moisture=45.0))
    db.commit()
    DatasetService.build_from_observation(db, db.get(Observation, "s1"))

    stats = DatasetRepository.stats(db, farm.farmer_id, [farm.id])
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


def test_alert_resolution() -> None:
    db = _memory_session()
    farm, node = _farm_with_node(db)

    def reading(soil, ts=None):
        _, _, raised = observation_service.ingest_sensors(db, node, 30.0, 60.0, soil, 95.0, ts)
        return raised

    reading(10.0)                                   # dry -> soil_low opens
    open_q = db.query(Alert).filter(Alert.type == "soil_low", Alert.resolved.is_(False))
    assert open_q.count() == 1
    reading(21.0)                                   # in range but inside the clear margin
    assert open_q.count() == 1, "hysteresis: 21% must not clear (needs >= min + margin)"
    reading(25.0)                                   # clearly recovered -> auto-resolved
    assert open_q.count() == 0
    a = db.query(Alert).filter(Alert.type == "soil_low").one()
    assert a.resolved and a.resolved_at and a.resolution.startswith("auto: back in range")

    # Reconcile: an alert left open from before auto-resolution existed closes
    # against the node's latest reading, but only if that reading is newer.
    stale = Alert(farm_id=farm.id, node_id=node.id, type="humidity_high", severity="warning",
                  message="High humidity 90%", value=90.0, created_at=datetime(2026, 7, 26))
    future = Alert(farm_id=farm.id, node_id=node.id, type="temp_high", severity="warning",
                   message="High temperature 45C", value=45.0, created_at=datetime(2099, 1, 1))
    db.add_all([stale, future])
    db.commit()
    closed = alerts.reconcile_open_alerts(db)
    db.commit()
    assert stale in closed and stale.resolved          # latest reading: humidity 60%
    assert not future.resolved                          # reading predates it -> stays open

    # Low battery clears from a heartbeat once comfortably above the threshold.
    alerts.evaluate_battery(db, farm.id, node.id, 10.0)
    db.commit()
    alerts.evaluate_battery(db, farm.id, node.id, 80.0)
    db.commit()
    assert db.query(Alert).filter(Alert.type == "low_battery", Alert.resolved.is_(False)).count() == 0


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

    # Still silent -> no duplicate alert on the next timer tick.
    assert alerts.evaluate_offline(db) == []

    # The node makes contact again -> online, and its offline alert is resolved.
    _health, closed = alerts.mark_seen(db, node.id)
    db.commit()
    assert db.get(NodeHealth, node.id).status == "online"
    assert [a.type for a in closed] == ["node_offline"]
    assert closed[0].resolved and closed[0].resolution == "auto: node back online"
    assert alerts.evaluate_offline(db) == []      # fresh contact -> stays online


if __name__ == "__main__":
    test_language_detection_and_routing()
    test_password_and_token()
    test_context_engine_and_prompt()
    test_crop_doctor_prompt_and_intents()
    test_knowledge_retrieval()
    test_claim_check()
    test_llm_failure_is_not_saved()
    test_compact_prompt_for_finetuned_model()
    test_orchestrator_and_memory()
    test_health_score()
    test_speech_provider()
    test_voice_loop_grounded()
    test_dataset_generation_and_quality()
    test_label_generation()
    test_export_filtering_and_versioning()
    test_dataset_stats_and_conversation_linking()
    test_merge_and_alerts()
    test_alert_resolution()
    test_offline_detection()
    print("OK — all self-checks passed")
