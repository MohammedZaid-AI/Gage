"""Structured prompt builder — the AI Crop Doctor.

The ONLY place farm data becomes prompt text; routers and services never
concatenate prompts. Produces a sectioned prompt that turns Gage into an
experienced agricultural field officer: it states Observed Facts, then separate
Inference, a Confidence level, and Recommendations — and refuses to guess when
the evidence is thin.
"""
from backend.ai.knowledge import KnowledgeDoc
from backend.config import get_settings
from backend.models import Observation
from backend.services.farm_context import FarmContext, Trend

# --- persona + response contract (the "system" the model must follow) ---
_PERSONA = (
    "You are Gage, an experienced agricultural field officer who advises sugarcane "
    "farmers in Karnataka (Kannada and English). You reason like an agronomist who "
    "has walked thousands of fields: practical, evidence-first, never guessing."
)

_RESPONSE_CONTRACT = (
    "Answer EVERY question using exactly these four sections, in this order:\n"
    "Observation: what the data currently shows — Observed Facts only (numbers, "
    "vision, alerts). No interpretation here.\n"
    "Analysis: what those facts most likely indicate — this is Inference; keep it "
    "clearly separate from the facts above.\n"
    "Confidence: exactly one of High, Medium, or Low, with a one-line reason.\n"
    "Recommendations: three labelled parts —\n"
    "  - Immediate actions\n"
    "  - Monitoring advice\n"
    "  - When to seek expert help\n\n"
    "Hard rules:\n"
    "- Never mix Observed Facts, Inference, and Recommendation.\n"
    "- If the evidence is insufficient, reply exactly: \"I don't have enough "
    "evidence from the latest observation.\" then name what is missing. Do not guess.\n"
    "- If there are active alerts, address them FIRST.\n"
    "- If the vision summary and the sensor readings disagree, state the "
    "uncertainty explicitly rather than picking one.\n"
    "- If VISION EVIDENCE says NOT IDENTIFIED or NO IMAGE, you MUST NOT name any "
    "disease from the image. Say the image could not be confidently identified, and "
    "reason from sensors only.\n"
    "- A classification is evidence, not ground truth. Write \"the image was "
    "classified as X (N% confidence)\" or \"resembles X\" — never \"the crop has X\". "
    "Do not estimate severity or spread from one photo, and do not prescribe "
    "treatment on the classifier alone.\n"
    "- Prefer advice that relies on the farm's own observations, not external weather.\n"
    "- Reply in the farmer's language: Kannada if they wrote Kannada, else English."
)

# --- intent-specific focus (the "prompt templates") ---
_INTENT_TEMPLATES = {
    "disease": "Diagnose likely sugarcane diseases (red rot, smut, rust, leaf spot) "
               "from leaf colour, lesions, and humidity. Advise isolation/removal and "
               "when to consult a plant pathologist.",
    "irrigation": "Judge irrigation timing from the soil-moisture level and its trend "
                  "and the crop stage. Say whether to irrigate now, wait, or hold, and why.",
    "fertilizer": "Assess nutrient status from leaf colour (yellowing => possible "
                  "nitrogen deficiency) and growth. Recommend a soil/leaf test before "
                  "heavy fertiliser; give dosing guidance only if clearly warranted.",
    "pest": "Look for pest pressure (borer holes, chewed leaves, discoloration). Advise "
            "scouting and integrated pest management; chemical control only if justified.",
    "growth": "Evaluate canopy density and growth-stage progress versus history. Advise "
              "on tillering / grand-growth management.",
    "weather": "Give advice that depends only on this farm's own observations, not on "
               "external weather forecasts.",
    "general": "Answer the farmer's question grounded strictly in this farm's data.",
}

_INTENT_KEYWORDS = {
    # Includes the classifier's own class names, so a farmer who repeats the
    # verdict back ("is this smut?") lands on the disease template.
    "disease": ("disease", "red rot", "smut", "rust", "fungus", "infect", "lesion",
                "spot", "rot", "pokkah", "boeng", "chlorosis", "grassy", "whip",
                "mosaic", "viral", "ರೋಗ"),
    "irrigation": ("irrigat", "water", "moisture", "dry", "drought", "ನೀರು"),
    "fertilizer": ("fertil", "nutrient", "urea", "nitrogen", "manure", "npk", "ಗೊಬ್ಬರ"),
    "pest": ("pest", "insect", "borer", "worm", "aphid", "caterpillar", "ಕೀಟ"),
    "growth": ("grow", "tiller", "canopy", "height", "yield", "stage", "ಬೆಳವಣಿಗೆ"),
    "weather": ("weather", "rain", "forecast", "climate"),
}


def detect_intent(question: str) -> str:
    q = question.lower()
    for intent, kws in _INTENT_KEYWORDS.items():
        if any(kw in q for kw in kws):
            return intent
    return "general"


# --- section rendering ---
def _fmt(v: float | None, unit: str) -> str:
    return f"{v}{unit}" if v is not None else "n/a"


def _vision_block(obs: Observation | None) -> str:
    """The classifier verdict as structured, citable evidence — or an explicit
    statement that no diagnosis exists, which the contract forbids the model from
    filling in. `vision_label` is NULL whenever the model abstained.
    """
    if obs is None or not obs.image_path:
        return ("- Status: NO IMAGE — no photo was captured for this observation.\n"
                "- Rule: do not describe or diagnose anything visual. Use sensors only.")
    if not obs.vision_label:
        return (
            "- Classification: NONE\n"
            "- Status: NOT IDENTIFIED — the image was not classified (the model "
            "abstained, or no classifier is loaded).\n"
            "- Rule: you MUST NOT name any disease or condition from this image. Say "
            "plainly that the image could not be confidently identified, and reason "
            "from the sensor readings only."
        )
    conf = (f"{obs.vision_confidence:.2f} ({obs.vision_confidence * 100:.0f}%)"
            if obs.vision_confidence is not None else "unknown")
    return (
        f"- Classification: {obs.vision_label.replace('_', ' ')}\n"
        f"- Confidence: {conf}\n"
        "- Model: Gage sugarcane image classifier (11 classes, single-image, "
        "trained on leaf/cane photographs)\n"
        "- Status: classified\n"
        "- Rule: this is what the image RESEMBLES, not a confirmed diagnosis. State "
        "it as a classification with its confidence, never as established fact. The "
        "model sees one photo: it cannot judge severity, how far the problem has "
        "spread, or the state of the rest of the field."
    )


def _observation_block(obs: Observation | None) -> str:
    if obs is None:
        return "No observation recorded yet."
    return (
        f"- Time: {obs.timestamp:%Y-%m-%d %H:%M} UTC (node {obs.node_id})\n"
        f"- Vision: {obs.vision_summary or 'no image analysed'}\n"
        f"- Temperature: {_fmt(obs.temperature, ' C')}\n"
        f"- Humidity: {_fmt(obs.humidity, ' %')}\n"
        f"- Soil moisture: {_fmt(obs.soil_moisture, ' %')}\n"
        f"- GPS: {_fmt(obs.gps_lat, '')}, {_fmt(obs.gps_long, '')}"
    )


def _sensor_source(ctx: FarmContext) -> Observation | None:
    """Where the freshest sensor values live — the SensorReading log, not ctx.latest.

    An Observation only carries sensor columns when a reading merged into it
    inside the merge window, so an image-only newest observation reports n/a
    while a fresh reading sits unused. Falls back to the observation's own merged
    values when the farm has no SensorReading rows (directly seeded or imported
    data), and returns None when there is genuinely nothing to report.

    Both types expose temperature/humidity/soil_moisture/timestamp, so callers
    read the result the same way either way.
    """
    if ctx.latest_reading is not None:
        return ctx.latest_reading
    obs = ctx.latest
    if obs is not None and any(v is not None for v in
                               (obs.temperature, obs.humidity, obs.soil_moisture)):
        return obs
    return None


def _sensor_block(ctx: FarmContext) -> str:
    src = _sensor_source(ctx)
    if src is None:
        return "No sensor reading recorded yet for this farm."
    lines = [
        f"- Taken: {src.timestamp:%Y-%m-%d %H:%M} UTC",
        f"- Temperature: {_fmt(src.temperature, ' C')}",
        f"- Humidity: {_fmt(src.humidity, ' %')}",
        f"- Soil moisture: {_fmt(src.soil_moisture, ' %')}",
    ]
    # Say so when the readings and the image are separate events, so the model
    # cannot present them as one moment in the field.
    obs = ctx.latest
    if obs is not None and getattr(src, "observation_id", obs.id) != obs.id:
        lines.append("- Note: these readings come from a separate capture, not from "
                     "the same moment as the observation above.")
    return "\n".join(lines)


def _trend_line(t: Trend) -> str:
    word = {"up": "increased", "down": "decreased", "flat": "unchanged"}[t.direction]
    return (f"- {t.metric.replace('_', ' ').capitalize()} {word} by "
            f"{abs(t.delta)}{t.unit} compared to {t.since} "
            f"({t.previous}{t.unit} -> {t.current}{t.unit}).")


def _history_block(ctx: FarmContext) -> str:
    lines: list[str] = []
    if ctx.trends:
        lines.append("Trends (compare current vs earlier observation):")
        lines += [_trend_line(t) for t in ctx.trends]
    else:
        lines.append("Only one observation on record — no comparison possible yet.")
    if len(ctx.recent) > 1:
        lines.append(f"Observations on record: {len(ctx.recent)} (most recent first).")
    return "\n".join(lines)


def _alerts_block(ctx: FarmContext) -> str:
    if not ctx.active_alerts:
        return "No active alerts."
    return ("Address these FIRST:\n"
            + "\n".join(f"- [{a.severity}] {a.message}" for a in ctx.active_alerts))


def _consistency_note(ctx: FarmContext) -> str:
    """Flag vision/sensor disagreement deterministically so the model can hedge."""
    obs = ctx.latest
    if obs is None:
        return ""
    s = get_settings()
    looks_healthy = (obs.vision_label == "healthy" if obs.vision_label
                     else "healthy" in (obs.vision_summary or "").lower())
    # Sensors come from the same source as the SENSOR READINGS block, not from
    # the observation: an image-only observation carries no sensor columns, which
    # would silently disable this check in exactly the case it exists for — a
    # photo and a reading arriving as separate captures.
    src = _sensor_source(ctx)
    sensor_stress = src is not None and (
        (src.soil_moisture is not None and src.soil_moisture < s.soil_moisture_min)
        or (src.humidity is not None and src.humidity > s.humidity_max)
        or (src.temperature is not None and src.temperature > s.temperature_max)
    )
    if looks_healthy and sensor_stress:
        return ("\n\n# SIGNAL CHECK\nVision suggests healthy foliage, but sensor "
                "readings indicate stress. Treat the diagnosis as uncertain and say so.")
    return ""


def _knowledge_block(docs: list[KnowledgeDoc]) -> str:
    if not docs:
        return "No specific knowledge-base entry matched this question."
    return "\n\n".join(f"{d.title}:\n{d.text}" for d in docs)


def _conversation_block(ctx: FarmContext) -> str:
    if not ctx.conversation:
        return ""
    turns = "\n".join(f"Farmer: {c.question}\nGage: {c.answer}" for c in ctx.conversation)
    return f"\n\n# CONVERSATION MEMORY (recent turns, for context)\n{turns}"


def build(ctx: FarmContext, docs: list[KnowledgeDoc], question: str) -> str:
    """Assemble the full structured Crop Doctor prompt for the LLM."""
    intent = detect_intent(question)
    latest = ctx.latest
    return (
        f"{_PERSONA}\n\n{_RESPONSE_CONTRACT}\n\n"
        f"# FOCUS FOR THIS QUESTION ({intent})\n{_INTENT_TEMPLATES[intent]}\n\n"
        f"# FARM\n"
        f"Name: {ctx.farm.name}\n"
        f"Crop: {ctx.crop_type}\n"
        f"Location: {ctx.location}\n"
        f"Farmer: {ctx.farmer.name or 'unknown'}\n\n"
        f"# CURRENT OBSERVATION\n{_observation_block(latest)}\n\n"
        f"# VISION EVIDENCE (image classifier)\n{_vision_block(latest)}\n\n"
        f"# SENSOR READINGS (latest)\n{_sensor_block(ctx)}\n\n"
        f"# RECENT HISTORY\n{_history_block(ctx)}\n\n"
        f"# ACTIVE ALERTS\n{_alerts_block(ctx)}\n\n"
        f"# AGRICULTURAL KNOWLEDGE\n{_knowledge_block(docs)}"
        f"{_consistency_note(ctx)}"
        f"{_conversation_block(ctx)}\n\n"
        f"# USER QUESTION\n{question}"
    )
