"""LabelGenerator — automatic labels for a dataset entry, derived from sensor
thresholds and active alerts. No AI/ML; deterministic rules so labels are
reproducible and auditable.
"""
from backend.config import get_settings
from backend.models import Observation

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
