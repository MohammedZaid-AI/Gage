"""Structured prompt builder. The ONLY place farm data becomes prompt text —
routers and services must never concatenate prompt strings themselves.

Produces a sectioned prompt (# FARM, # CURRENT OBSERVATION, # SENSOR READINGS,
# RECENT HISTORY, # ACTIVE ALERTS, # AGRICULTURAL KNOWLEDGE, # USER QUESTION)
plus grounding rules that force the model to separate Observed Facts from
Recommendations and never invent data it wasn't given.
"""
from backend.ai.knowledge import KnowledgeDoc
from backend.models import Observation
from backend.services.farm_context import FarmContext, Trend

_GROUNDING_RULES = (
    "You are Gage, an AI assistant for this specific farm. Follow these rules:\n"
    "1. Answer ONLY from the farm data below and the agricultural knowledge provided.\n"
    "2. Never invent observations, sensor values, or history that are not shown.\n"
    "3. If the data is insufficient to answer, say so plainly.\n"
    "4. Structure every answer as two labelled sections:\n"
    "   Observed: bullet points of facts from the data.\n"
    "   Recommendation: bullet points of advice grounded in those facts.\n"
    "5. Reply in the farmer's language (Kannada if they wrote in Kannada, else English)."
)


def _fmt(v: float | None, unit: str) -> str:
    return f"{v}{unit}" if v is not None else "n/a"


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


def _trend_line(t: Trend) -> str:
    word = {"up": "increased", "down": "decreased", "flat": "unchanged"}[t.direction]
    return (f"- {t.metric.replace('_', ' ').capitalize()} {word} by "
            f"{abs(t.delta)}{t.unit} vs the previous observation "
            f"({t.previous}{t.unit} -> {t.current}{t.unit}).")


def _history_block(ctx: FarmContext) -> str:
    lines: list[str] = []
    if ctx.trends:
        lines.append("Trends:")
        lines += [_trend_line(t) for t in ctx.trends]
    else:
        lines.append("Not enough history to compute trends yet.")
    if len(ctx.recent) > 1:
        lines.append(f"Observations on record: {len(ctx.recent)} (most recent first).")
    return "\n".join(lines)


def _alerts_block(ctx: FarmContext) -> str:
    if not ctx.active_alerts:
        return "No active alerts."
    return "\n".join(f"- [{a.severity}] {a.message}" for a in ctx.active_alerts)


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
    """Assemble the full structured prompt string for the LLM."""
    return (
        f"{_GROUNDING_RULES}\n\n"
        f"# FARM\n"
        f"Name: {ctx.farm.name}\n"
        f"Crop: {ctx.crop_type}\n"
        f"Location: {ctx.location}\n"
        f"Farmer: {ctx.farmer.name or 'unknown'}\n\n"
        f"# CURRENT OBSERVATION\n{_observation_block(ctx.latest)}\n\n"
        f"# SENSOR READINGS (latest)\n"
        f"- Temperature: {_fmt(ctx.latest.temperature if ctx.latest else None, ' C')}\n"
        f"- Humidity: {_fmt(ctx.latest.humidity if ctx.latest else None, ' %')}\n"
        f"- Soil moisture: {_fmt(ctx.latest.soil_moisture if ctx.latest else None, ' %')}\n\n"
        f"# RECENT HISTORY\n{_history_block(ctx)}\n\n"
        f"# ACTIVE ALERTS\n{_alerts_block(ctx)}\n\n"
        f"# AGRICULTURAL KNOWLEDGE\n{_knowledge_block(docs)}"
        f"{_conversation_block(ctx)}\n\n"
        f"# USER QUESTION\n{question}"
    )
