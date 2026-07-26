"""LabelGenerator — automatic labels for a dataset entry, derived from the
vision summary, sensor thresholds, and active alerts. No AI/ML; deterministic
rules so labels are reproducible and auditable.
"""
import re

from backend.config import get_settings
from backend.models import Observation

# Skip vision keywords inside a negated clause ("No yellowing", "free of pests")
# so we don't mislabel a healthy plant as diseased — bad supervised labels.
_NEGATIONS = ("no ", "not ", "without", "n't", "free of", "absent", "none")

# Vision keyword -> label.
_VISION_LABELS = {
    "healthy": "healthy",
    "yellow": "possible_disease",
    "disease": "possible_disease",
    "pest": "possible_disease",
    "weed": "weed_growth",
    "sparse": "water_stress",
    "stressed": "water_stress",
    "wilt": "water_stress",
}

# Alert type -> label.
_ALERT_LABELS = {
    "soil_low": "dry_soil",
    "humidity_high": "high_humidity",
    "temp_high": "heat_stress",
}


class LabelGenerator:
    @staticmethod
    def generate(obs: Observation, active_alerts: list[str]) -> list[str]:
        s = get_settings()
        labels: set[str] = set()

        # Evaluate vision keywords per clause, skipping negated clauses.
        for clause in re.split(r"[.;\n]", (obs.vision_summary or "").lower()):
            if any(neg in clause for neg in _NEGATIONS):
                continue
            for kw, label in _VISION_LABELS.items():
                if kw in clause:
                    labels.add(label)

        if obs.soil_moisture is not None and obs.soil_moisture < s.soil_moisture_min:
            labels.update({"dry_soil", "water_stress"})
        if obs.humidity is not None and obs.humidity > s.humidity_max:
            labels.add("high_humidity")

        for alert_type in active_alerts:
            if alert_type in _ALERT_LABELS:
                labels.add(_ALERT_LABELS[alert_type])

        if not labels:
            labels.add("normal_growth")
        return sorted(labels)
