"""Rule-based farm health score. 100 = healthy; deduct for stress signals.

No ML — a transparent rule engine the farmer (and we) can reason about. Operates
on a FarmContext snapshot so it sees the same data the AI does.
"""
from dataclasses import dataclass

from backend.ai.base import DISEASED
from backend.config import get_settings
from backend.services.farm_context import FarmContext

_ANOMALY_WORDS = ("yellow", "disease", "stress", "sparse", "pest", "wilt", "brown")


@dataclass(frozen=True)
class HealthScore:
    score: int
    status: str            # Healthy | Watch | Critical
    reasons: list[str]


def _status(score: int) -> str:
    if score >= 80:
        return "Healthy"
    if score >= 60:
        return "Watch"
    return "Critical"


def compute(ctx: FarmContext) -> HealthScore:
    s = get_settings()
    score = 100
    reasons: list[str] = []
    obs = ctx.latest

    if obs is None:
        return HealthScore(0, "Unknown", ["No observations recorded yet."])

    if obs.soil_moisture is not None and obs.soil_moisture < s.soil_moisture_min:
        score -= 20
        reasons.append(f"Low soil moisture ({obs.soil_moisture:.0f}%).")
    if obs.humidity is not None and obs.humidity > s.humidity_max:
        score -= 15
        reasons.append(f"High humidity ({obs.humidity:.0f}%).")
    if obs.temperature is not None and obs.temperature > s.temperature_max:
        score -= 15
        reasons.append(f"High temperature ({obs.temperature:.0f}C).")

    # A classifier verdict outranks keyword matching on its own prose. Deduct in
    # proportion to confidence so a hesitant call cannot tank the score outright.
    if obs.vision_label:
        if obs.vision_label in DISEASED:
            conf = obs.vision_confidence if obs.vision_confidence is not None else 1.0
            score -= round(20 * conf)
            reasons.append(f"Vision: {obs.vision_label.replace('_', ' ')} "
                           f"({conf * 100:.0f}% confidence).")
    else:
        vision = (obs.vision_summary or "").lower()
        hits = [w for w in _ANOMALY_WORDS if w in vision]
        if hits:
            score -= 15
            reasons.append(f"Vision anomaly ({', '.join(hits)}).")

    if ctx.active_alerts:
        penalty = min(len(ctx.active_alerts) * 5, 25)
        score -= penalty
        reasons.append(f"{len(ctx.active_alerts)} active alert(s).")

    score = max(0, min(100, score))
    if not reasons:
        reasons.append("All monitored indicators within normal range.")
    return HealthScore(score, _status(score), reasons)
