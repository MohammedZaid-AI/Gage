"""Observation service: merge the phone's image and the ESP32's sensor reading
into ONE observation per capture, and decide when an AI summary is worth making.

This is the only place hardware data meets the AI facade. The node routers call
this service; they never import AI providers directly, keeping AI independent of
hardware (Observation -> AI stays a one-way pipeline). Images are stored as field
records only; nothing analyses them.

Merge strategy: an incoming image/sensor reading is folded into the most recent
observation from the same node that is still missing that modality and is within
`merge_window_seconds`; otherwise a fresh observation is started.

Summary trigger: a reading that raises a NEW alert, or the farm's newest summary
being older than SUMMARY_INTERVAL_MINUTES (default 60). Not every reading: the
ESP32 posts every 30 s. Alerts alone are not enough because they de-duplicate
while open and are never auto-resolved, so each type fires only once. The
summary runs in a background thread after the response is sent, never inside
the sensor request.
"""
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai import claim_check, summarize_observation
from backend.config import get_settings
from backend.database import SessionLocal
from backend.dataset.service import DatasetService
from backend.models import Alert, Farm, Observation, SensorReading, _now
from backend.services import alerts

logger = logging.getLogger("gage.observation_service")


def _build_dataset_entry(db: Session, obs: Observation) -> None:
    """Feed the observation to the Dataset Builder. Best-effort: a dataset hiccup
    must never break observation ingest."""
    try:
        DatasetService.build_from_observation(db, obs)
    except Exception:
        logger.exception("dataset entry build failed for observation %s", obs.id)

_IMAGE_DIR = Path(get_settings().image_dir)
_IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def _age_seconds(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return (datetime.utcnow() - dt).total_seconds()


def _mergeable(db: Session, node_id: str, adding: str) -> Observation | None:
    """Most recent observation for this node that still needs `adding`
    ('image' | 'sensors') and is within the merge window, else None."""
    latest = db.execute(
        select(Observation)
        .where(Observation.node_id == node_id)
        .order_by(Observation.timestamp.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return None
    age = _age_seconds(latest.timestamp)
    if age is None or age > get_settings().merge_window_seconds:
        return None
    if adding == "image" and latest.image_path is None:
        return latest
    if adding == "sensors" and latest.temperature is None:
        return latest
    return None


def _obs_context(obs: Observation, farm: Farm | None, open_alerts: list[str]) -> str:
    def fmt(v: float | None, unit: str) -> str:
        return f"{v}{unit}" if v is not None else "n/a"

    return (
        f"Farm: {farm.name if farm else obs.farm_id}\n"
        f"- Temperature: {fmt(obs.temperature, ' C')}\n"
        f"- Humidity: {fmt(obs.humidity, ' %')}\n"
        f"- Soil moisture: {fmt(obs.soil_moisture, ' %')}\n"
        f"- Active alerts: {'; '.join(open_alerts) or 'none'}"
    )


def summary_due(db: Session, obs: Observation, raised: list[Alert]) -> bool:
    """Whether this sensor observation should get an AI summary (see module doc)."""
    if all(v is None for v in (obs.temperature, obs.humidity, obs.soil_moisture)):
        return False
    if obs.ai_summary:
        return False
    if raised:
        return True
    last = db.execute(
        select(Observation.timestamp)
        .where(Observation.farm_id == obs.farm_id, Observation.ai_summary.is_not(None))
        .order_by(Observation.timestamp.desc()).limit(1)
    ).scalar_one_or_none()
    age = _age_seconds(last)
    return age is None or age >= get_settings().summary_interval_minutes * 60


_summarizing: set[int] = set()   # farm ids with a summary in flight
_summarizing_lock = threading.Lock()


def generate_summary(observation_id: str, session_factory=SessionLocal) -> None:
    """Background task: summarise one observation with its own DB session.

    One in flight per farm, so readings arriving during a slow generation do not
    queue duplicates. A model failure saves nothing and is logged — a summary is
    never replaced by an error message.
    """
    with session_factory() as db:
        obs = db.get(Observation, observation_id)
        if obs is None or obs.ai_summary:
            return
        farm_id = obs.farm_id
        with _summarizing_lock:
            if farm_id in _summarizing:
                return
            _summarizing.add(farm_id)
        try:
            farm = db.get(Farm, farm_id)
            language = farm.farmer.language if farm and farm.farmer else "en"
            open_alerts = [a.message for a in db.execute(
                select(Alert).where(Alert.farm_id == farm_id, Alert.resolved.is_(False))
            ).scalars()]
            context = _obs_context(obs, farm, open_alerts)
            text = summarize_observation(context, language)
            obs.ai_summary = claim_check.check(text, context, language).answer
            db.commit()
            db.refresh(obs)
            _build_dataset_entry(db, obs)
            logger.info("AI summary generated for observation %s", obs.id)
        except Exception:
            db.rollback()
            logger.exception("AI summary failed for observation %s; nothing saved", observation_id)
        finally:
            with _summarizing_lock:
                _summarizing.discard(farm_id)


def ingest_image(
    db: Session,
    node,
    image_bytes: bytes,
    filename: str | None,
    gps_lat: float | None,
    gps_long: float | None,
    timestamp: datetime | None,
) -> Observation:
    obs = _mergeable(db, node.id, "image")
    if obs is None:
        obs = Observation(
            id=uuid.uuid4().hex, farm_id=node.farm_id, node_id=node.id,
            timestamp=timestamp or _now(),
        )
        db.add(obs)
        db.flush()

    suffix = Path(filename or "").suffix or ".jpg"
    dest = _IMAGE_DIR / f"{obs.id}{suffix}"
    dest.write_bytes(image_bytes)
    obs.image_path = dest.as_posix()
    if gps_lat is not None:
        obs.gps_lat = gps_lat
    if gps_long is not None:
        obs.gps_long = gps_long

    db.commit()
    db.refresh(obs)
    _build_dataset_entry(db, obs)
    logger.info("image merged into observation %s (node=%s)", obs.id, node.id)
    return obs


def ingest_sensors(
    db: Session,
    node,
    temperature: float | None,
    humidity: float | None,
    soil_moisture: float | None,
    battery: float | None,
    timestamp: datetime | None,
) -> tuple[Observation, SensorReading, list[Alert]]:
    reading = SensorReading(
        node_id=node.id, farm_id=node.farm_id,
        temperature=temperature, humidity=humidity,
        soil_moisture=soil_moisture, battery=battery,
        timestamp=timestamp or _now(),
    )
    db.add(reading)

    obs = _mergeable(db, node.id, "sensors")
    if obs is None:
        obs = Observation(
            id=uuid.uuid4().hex, farm_id=node.farm_id, node_id=node.id,
            timestamp=timestamp or _now(),
        )
        db.add(obs)
        db.flush()
    obs.temperature = temperature
    obs.humidity = humidity
    obs.soil_moisture = soil_moisture
    db.flush()
    reading.observation_id = obs.id

    raised = alerts.evaluate_reading(db, reading)
    db.commit()
    db.refresh(obs)
    db.refresh(reading)
    _build_dataset_entry(db, obs)
    logger.info("sensors merged into observation %s (node=%s, %d alert(s))",
                obs.id, node.id, len(raised))
    return obs, reading, raised
