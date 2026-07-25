"""Farm Context Engine — the ONE place that assembles everything the AI needs
about a farm before any prompt is built. Nothing else in the backend should
gather AI context or read these tables for prompting purposes.

`build()` returns an immutable FarmContext snapshot: farmer, farm, crop, location,
latest + recent observations, latest sensor reading, active alerts, recent
conversation (memory), and computed sensor trends (latest vs previous observation).
"""
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import (
    Alert,
    Conversation,
    Farm,
    Farmer,
    Observation,
    SensorReading,
)

RECENT_OBSERVATIONS = 10
RECENT_CONVERSATION = 5


@dataclass(frozen=True)
class Trend:
    metric: str            # soil_moisture | humidity | temperature
    current: float
    previous: float
    delta: float           # current - previous (rounded)
    direction: str         # up | down | flat

    @property
    def unit(self) -> str:
        return "C" if self.metric == "temperature" else "%"


@dataclass(frozen=True)
class FarmContext:
    farmer: Farmer
    farm: Farm
    latest: Observation | None
    recent: list[Observation]                 # newest first, up to RECENT_OBSERVATIONS
    latest_reading: SensorReading | None
    active_alerts: list[Alert]
    conversation: list[Conversation]          # oldest first (chat memory)
    trends: list[Trend] = field(default_factory=list)

    @property
    def crop_type(self) -> str:
        return self.farm.crop_type

    @property
    def location(self) -> str:
        parts = [p for p in (self.farm.village,) if p]
        return ", ".join(parts) if parts else "unknown"


def _trends(recent: list[Observation]) -> list[Trend]:
    """Compare the latest observation with the previous one, per sensor metric."""
    if len(recent) < 2:
        return []
    cur, prev = recent[0], recent[1]
    out: list[Trend] = []
    for metric in ("soil_moisture", "humidity", "temperature"):
        c, p = getattr(cur, metric), getattr(prev, metric)
        if c is None or p is None:
            continue
        delta = round(c - p, 1)
        direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
        out.append(Trend(metric, c, p, delta, direction))
    return out


def build(db: Session, farm: Farm) -> FarmContext:
    recent = list(db.execute(
        select(Observation)
        .where(Observation.farm_id == farm.id)
        .order_by(Observation.timestamp.desc())
        .limit(RECENT_OBSERVATIONS)
    ).scalars())

    latest_reading = db.execute(
        select(SensorReading)
        .where(SensorReading.farm_id == farm.id)
        .order_by(SensorReading.timestamp.desc())
        .limit(1)
    ).scalar_one_or_none()

    active_alerts = list(db.execute(
        select(Alert)
        .where(Alert.farm_id == farm.id, Alert.resolved.is_(False))
        .order_by(Alert.created_at.desc())
    ).scalars())

    conversation = list(db.execute(
        select(Conversation)
        .where(Conversation.farm_id == farm.id)
        .order_by(Conversation.timestamp.desc())
        .limit(RECENT_CONVERSATION)
    ).scalars())
    conversation.reverse()  # oldest first for natural reading order

    return FarmContext(
        farmer=farm.farmer,
        farm=farm,
        latest=recent[0] if recent else None,
        recent=recent,
        latest_reading=latest_reading,
        active_alerts=active_alerts,
        conversation=conversation,
        trends=_trends(recent),
    )
