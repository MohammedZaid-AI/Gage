"""Alert rule engine. Pure DB + config; no AI, no hardware coupling.

Rules (thresholds in config):
- humidity_high   : humidity > humidity_max
- soil_low        : soil_moisture < soil_moisture_min
- temp_high       : temperature > temperature_max
- low_battery     : battery < low_battery_percent
- node_offline    : last_seen older than offline_seconds

Alerts of the same (node, type) are de-duplicated while still unresolved, so a
persistently dry field raises one open alert, not one per reading.
"""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models import Alert, NodeHealth, SensorReading

logger = logging.getLogger("gage.alerts")


def _age_seconds(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:  # stored values may be naive (sqlite) or aware
        dt = dt.replace(tzinfo=None)
    return (datetime.utcnow() - dt).total_seconds()


def _has_open(db: Session, node_id: str | None, type_: str) -> bool:
    return db.execute(
        select(Alert.id).where(
            Alert.node_id == node_id, Alert.type == type_, Alert.resolved.is_(False)
        ).limit(1)
    ).first() is not None


def _raise(db: Session, farm_id: int, node_id: str | None, type_: str,
           severity: str, message: str, value: float | None) -> Alert | None:
    """Create an alert unless an identical one is already open. Returns it or None."""
    if _has_open(db, node_id, type_):
        return None
    alert = Alert(
        farm_id=farm_id, node_id=node_id, type=type_,
        severity=severity, message=message, value=value,
    )
    db.add(alert)
    logger.info("alert raised: %s node=%s value=%s", type_, node_id, value)
    return alert


def evaluate_reading(db: Session, reading: SensorReading) -> list[Alert]:
    """Threshold rules against one sensor reading. Caller commits."""
    s = get_settings()
    out: list[Alert] = []

    def add(a: Alert | None) -> None:
        if a is not None:
            out.append(a)

    if reading.humidity is not None and reading.humidity > s.humidity_max:
        add(_raise(db, reading.farm_id, reading.node_id, "humidity_high", "warning",
                   f"High humidity {reading.humidity:.0f}% (disease risk)", reading.humidity))
    if reading.soil_moisture is not None and reading.soil_moisture < s.soil_moisture_min:
        add(_raise(db, reading.farm_id, reading.node_id, "soil_low", "warning",
                   f"Low soil moisture {reading.soil_moisture:.0f}% (water stress)",
                   reading.soil_moisture))
    if reading.temperature is not None and reading.temperature > s.temperature_max:
        add(_raise(db, reading.farm_id, reading.node_id, "temp_high", "warning",
                   f"High temperature {reading.temperature:.0f}C (heat stress)",
                   reading.temperature))
    if reading.battery is not None and reading.battery < s.low_battery_percent:
        add(_raise(db, reading.farm_id, reading.node_id, "low_battery", "critical",
                   f"Low node battery {reading.battery:.0f}%", reading.battery))
    return out


def evaluate_battery(db: Session, farm_id: int, node_id: str,
                     battery: float | None) -> list[Alert]:
    """Low-battery rule from a heartbeat. Caller commits."""
    s = get_settings()
    if battery is not None and battery < s.low_battery_percent:
        a = _raise(db, farm_id, node_id, "low_battery", "critical",
                   f"Low node battery {battery:.0f}%", battery)
        return [a] if a else []
    return []


def evaluate_offline(db: Session) -> list[Alert]:
    """Mark stale nodes offline and raise one alert each. Evaluated lazily on read.
    ponytail: lazy (runs when status is queried). Move to a scheduled task when you
    need offline alerts without a dashboard viewer."""
    s = get_settings()
    out: list[Alert] = []
    healths = list(db.execute(select(NodeHealth)).scalars())
    for h in healths:
        age = _age_seconds(h.last_seen)
        offline = age is not None and age > s.offline_seconds
        if offline and h.status != "offline":
            h.status = "offline"
            node = h.node
            a = _raise(db, node.farm_id, node.id, "node_offline", "critical",
                       "Node offline (no heartbeat)", None)
            if a:
                out.append(a)
        elif not offline and h.status == "offline":
            h.status = "online"  # recovered
    return out
