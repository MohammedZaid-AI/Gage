"""QualityScorer — a transparent 0-100 score for how useful a dataset entry is
as training data. No AI, no ML: presence/completeness/recency rules only.
"""
from dataclasses import dataclass
from datetime import datetime

from backend.models import Observation

_VALID_VISION = True  # sentinel for readability below


@dataclass(frozen=True)
class Quality:
    score: int
    reason: str


def _age_days(ts: datetime | None) -> float | None:
    if ts is None:
        return None
    if ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)
    return (datetime.utcnow() - ts).total_seconds() / 86400.0


class QualityScorer:
    @staticmethod
    def score(obs: Observation) -> Quality:
        score = 0
        reasons: list[str] = []

        if obs.image_path:
            score += 25
        else:
            reasons.append("image missing")

        if obs.gps_lat is not None and obs.gps_long is not None:
            score += 15
        else:
            reasons.append("missing GPS")

        present = sum(v is not None for v in
                      (obs.temperature, obs.humidity, obs.soil_moisture))
        score += 10 * present  # up to 30 for complete sensor readings
        if present < 3:
            reasons.append(f"{3 - present} sensor value(s) missing")

        vision = (obs.vision_summary or "").strip().lower()
        if vision and "unavailable" not in vision:
            score += 20
        else:
            reasons.append("no valid vision summary")

        age = _age_days(obs.timestamp)
        if age is not None and age <= 7:
            score += 10
        elif age is not None:
            reasons.append("stale timestamp")

        score = max(0, min(100, score))
        return Quality(score, "; ".join(reasons) if reasons else "complete")
