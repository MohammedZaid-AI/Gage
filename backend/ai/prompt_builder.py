"""Structured prompt builder — the AI Crop Doctor.

The ONLY place farm data becomes prompt text; routers and services never
concatenate prompts. Produces a sectioned prompt that turns Gage into an
experienced agricultural field officer: it states Observed Facts, then separate
Inference, a Confidence level, and Recommendations — and refuses to guess when
the evidence is thin.
"""
from backend.ai.knowledge import KnowledgeDoc
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
    "Observation: what the data currently shows — Observed Facts only (sensor "
    "numbers, trends, alerts). No interpretation here.\n"
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
    "- Gage does not analyse photos. Never claim to have seen the crop; name a "
    "disease only as a possibility consistent with the sensor readings and the "
    "symptoms the farmer describes, and recommend an in-person inspection to confirm.\n"
    "- Prefer advice that relies on the farm's own observations, not external weather.\n"
    "- Reply in the farmer's language: Kannada if they wrote Kannada, else English."
)

# --- intent-specific focus (the "prompt templates") ---
_INTENT_TEMPLATES = {
    "disease": "Assess disease risk (red rot, smut, rust, leaf spot) from humidity, "
               "temperature, and the symptoms the farmer describes. Advise "
               "isolation/removal and when to consult a plant pathologist.",
    "irrigation": "Judge irrigation timing from the soil-moisture level and its trend "
                  "and the crop stage. Say whether to irrigate now, wait, or hold, and why.",
    "fertilizer": "Assess nutrient status from the leaf colour and growth the farmer "
                  "describes (yellowing => possible nitrogen deficiency). Recommend a "
                  "soil/leaf test before heavy fertiliser; give dosing guidance only if "
                  "clearly warranted.",
    "pest": "Ask about or interpret described signs of pest pressure (borer holes, "
            "chewed leaves, discoloration). Advise scouting and integrated pest "
            "management; chemical control only if justified.",
    "growth": "Evaluate growth-stage progress from the farmer's description and the "
              "sensor history. Advise on tillering / grand-growth management.",
    "weather": "Give advice that depends only on this farm's own observations, not on "
               "external weather forecasts.",
    "general": "Answer the farmer's question grounded strictly in this farm's data.",
}

_INTENT_KEYWORDS = {
    # Includes common sugarcane disease names, so "is this smut?" lands on the
    # disease template.
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


def _observation_block(obs: Observation | None) -> str:
    if obs is None:
        return "No observation recorded yet."
    return (
        f"- Time: {obs.timestamp:%Y-%m-%d %H:%M} UTC (node {obs.node_id})\n"
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


def _anomaly_block(ctx: FarmContext) -> str:
    """The latest FlyBrain sensor-pattern score as one plain sentence (or nothing)."""
    from backend.services.anomaly import describe

    sentence = describe(ctx.latest_anomaly)
    return f"# SENSOR PATTERN CHECK (FlyBrain)\n{sentence}\n\n" if sentence else ""


def _knowledge_block(docs: list[KnowledgeDoc]) -> str:
    if not docs:
        return "No specific knowledge-base entry matched this question."
    return "\n\n".join(f"{d.title}:\n{d.text}" for d in docs)


def _conversation_block(ctx: FarmContext) -> str:
    if not ctx.conversation:
        return ""
    turns = "\n".join(f"Farmer: {c.question}\nGage: {c.answer}" for c in ctx.conversation)
    return f"\n\n# CONVERSATION MEMORY (recent turns, for context)\n{turns}"


def build_compact(docs: list[KnowledgeDoc], question: str) -> tuple[str, str]:
    """(context, farmer turn) for the fine-tuned Sarvam-1 adapter: retrieved
    knowledge and the farmer's own question, nothing else.

    No farm sensor data is sent to this model. Readings in the context and
    readings appended to the question both tested worse than none (2026-10-04
    verification runs: the model answered the readings instead of the question).
    Sensor data still drives alerts and the health score, outside the model.
    """
    context = "\n\n".join(d.text for d in docs) if docs else "No knowledge-base entry matched."
    return context, question


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
        f"# SENSOR READINGS (latest)\n{_sensor_block(ctx)}\n\n"
        f"# RECENT HISTORY\n{_history_block(ctx)}\n\n"
        f"# ACTIVE ALERTS\n{_alerts_block(ctx)}\n\n"
        f"{_anomaly_block(ctx)}"
        f"# AGRICULTURAL KNOWLEDGE\n{_knowledge_block(docs)}"
        f"{_conversation_block(ctx)}\n\n"
        f"# USER QUESTION\n{question}"
    )
