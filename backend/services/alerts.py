"""Alert rule engine. Pure DB + config; no AI, no hardware coupling.

Rules (thresholds in config):
- humidity_high   : humidity > humidity_max
- soil_low        : soil_moisture < soil_moisture_min
- temp_high       : temperature > temperature_max
- low_battery     : battery < low_battery_percent
- node_offline    : last_seen older than offline_seconds

Alerts of the same (node, type) are de-duplicated while still unresolved, so a
persistently dry field raises one open alert, not one per reading.

Resolution: an open alert closes automatically when a newer reading is back
inside the safe range by a clear margin (hysteresis, see config), or when a
farmer resolves it by hand. `resolution` records which.
"""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models import Alert, NodeHealth, SensorReading, _now

logger = logging.getLogger("gage.alerts")


def _age_seconds(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:  # stored values may be naive (sqlite) or aware
        dt = dt.replace(tzinfo=None)
    return (datetime.utcnow() - dt).total_seconds()


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _open(db: Session, node_id: str | None, type_: str) -> list[Alert]:
    return list(db.execute(
        select(Alert).where(
            Alert.node_id == node_id, Alert.type == type_, Alert.resolved.is_(False)
        )
    ).scalars())


def _raise(db: Session, farm_id: int, node_id: str | None, type_: str,
           severity: str, message: str, value: float | None) -> Alert | None:
    """Create an alert unless an identical one is already open. Returns it or None."""
    if _open(db, node_id, type_):
        return None
    alert = Alert(
        farm_id=farm_id, node_id=node_id, type=type_,
        severity=severity, message=message, value=value,
    )
    db.add(alert)
    logger.info("alert raised: %s node=%s value=%s", type_, node_id, value)
    return alert


def resolve(alert: Alert, how: str) -> None:
    """Close one alert, recording when and how. Caller commits."""
    alert.resolved = True
    alert.resolved_at = _now()
    alert.resolution = how
    logger.info("alert resolved: #%d %s node=%s (%s)", alert.id or 0, alert.type,
                alert.node_id, how)


def _recovered_types(humidity: float | None, soil: float | None, temp: float | None,
                     battery: float | None) -> dict[str, str]:
    """Alert types whose condition these values show is over, with the reason."""
    s = get_settings()
    out = {}
    if humidity is not None and humidity <= s.humidity_max - s.humidity_clear_margin:
        out["humidity_high"] = f"humidity {humidity:g}%"
    if soil is not None and soil >= s.soil_moisture_min + s.soil_moisture_clear_margin:
        out["soil_low"] = f"soil moisture {soil:g}%"
    if temp is not None and temp <= s.temperature_max - s.temperature_clear_margin:
        out["temp_high"] = f"temperature {temp:g}C"
    if battery is not None and battery >= s.low_battery_percent + s.battery_clear_margin:
        out["low_battery"] = f"battery {battery:g}%"
    return out


def _resolve_recovered(db: Session, node_id: str, recovered: dict[str, str],
                       newer_than: datetime | None = None) -> list[Alert]:
    closed = []
    for type_, reason in recovered.items():
        for a in _open(db, node_id, type_):
            # Only a reading taken after the alert can show it is over.
            if newer_than is not None and _naive(a.created_at) > _naive(newer_than):
                continue
            resolve(a, f"auto: back in range ({reason})")
            closed.append(a)
    return closed


def evaluate_reading(db: Session, reading: SensorReading) -> list[Alert]:
    """Threshold rules against one sensor reading: raises new alerts, and resolves
    open ones this reading shows are over. Returns the newly raised alerts.
    Caller commits."""
    s = get_settings()
    _resolve_recovered(db, reading.node_id, _recovered_types(
        reading.humidity, reading.soil_moisture, reading.temperature, reading.battery))

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
    """Low-battery rule from a heartbeat (raise or resolve). Caller commits."""
    s = get_settings()
    _resolve_recovered(db, node_id, _recovered_types(None, None, None, battery))
    if battery is not None and battery < s.low_battery_percent:
        a = _raise(db, farm_id, node_id, "low_battery", "critical",
                   f"Low node battery {battery:.0f}%", battery)
        return [a] if a else []
    return []


def reconcile_open_alerts(db: Session) -> list[Alert]:
    """Apply the auto-resolve rule to alerts that are already open, using each
    node's latest sensor reading taken after the alert was raised. Heals alerts
    left open from before resolution existed. Caller commits."""
    closed: list[Alert] = []
    nodes = {a.node_id for a in db.execute(
        select(Alert).where(Alert.resolved.is_(False), Alert.node_id.is_not(None))
    ).scalars()}
    for node_id in nodes:
        latest = db.execute(
            select(SensorReading).where(SensorReading.node_id == node_id)
            .order_by(SensorReading.timestamp.desc()).limit(1)
        ).scalar_one_or_none()
        if latest is not None:
            closed += _resolve_recovered(db, node_id, _recovered_types(
                latest.humidity, latest.soil_moisture, latest.temperature, latest.battery),
                newer_than=latest.timestamp)
        health = db.get(NodeHealth, node_id)
        if health is not None and health.battery is not None:
            closed += _resolve_recovered(db, node_id, _recovered_types(
                None, None, None, health.battery), newer_than=health.updated_at)
    return closed


def mark_seen(db: Session, node_id: str) -> tuple[NodeHealth, list[Alert]]:
    """A node just contacted the server (heartbeat, sensors or photo): it is
    online, and any open node_offline alert for it is resolved. Returns the
    health row and the alerts closed. Caller commits."""
    health = db.get(NodeHealth, node_id) or NodeHealth(node_id=node_id)
    health.status = "online"
    health.last_seen = _now()
    health.updated_at = _now()
    db.add(health)
    closed = []
    for a in _open(db, node_id, "node_offline"):
        resolve(a, "auto: node back online")
        closed.append(a)
    return health, closed


def evaluate_offline(db: Session) -> list[Alert]:
    """Mark nodes silent for longer than offline_seconds as offline and raise one
    node_offline alert each. Run on a timer by the server (see backend/main.py);
    recovery is handled by mark_seen when the node next makes contact. Returns
    the newly raised alerts. Caller commits."""
    s = get_settings()
    out: list[Alert] = []
    healths = list(db.execute(select(NodeHealth)).scalars())
    for h in healths:
        age = _age_seconds(h.last_seen)
        if age is not None and age > s.offline_seconds and h.status != "offline":
            h.status = "offline"
            node = h.node
            logger.info("node %s offline: no contact for %.0fs", node.id, age)
            a = _raise(db, node.farm_id, node.id, "node_offline", "critical",
                       f"Node offline (no contact for {age / 60:.0f} min)", None)
            if a:
                out.append(a)
    return out
