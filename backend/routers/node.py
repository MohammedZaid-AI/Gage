"""Monitoring-node device API (authenticated by X-Node-Key).

Two physically independent devices talk to these endpoints:
- the Android phone  -> POST /node/image   (image + GPS)
- the ESP32          -> POST /node/sensors  (temperature/humidity/soil/battery)
Both -> POST /node/heartbeat. The backend merges image + sensors into one
observation (see services.observation_service). Never anonymous: get_node
requires a valid API key.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.dependencies import get_node
from backend.models import (
    Alert,
    NodeHealth,
    NodeHeartbeat,
    Observation,
    SensorReading,
    _now,
)
from backend.realtime import broadcaster
from backend.schemas import (
    AlertOut,
    HeartbeatIn,
    NodeHealthOut,
    ObservationOut,
    SensorIn,
    SensorReadingOut,
)
from backend.services import alerts, observation_service

logger = logging.getLogger("gage.node")
router = APIRouter(prefix="/node", tags=["node"])


def _obs_json(obs: Observation) -> dict:
    return ObservationOut.model_validate(obs).model_dump(mode="json")


@router.post("/image", response_model=ObservationOut)
async def upload_image(
    image: UploadFile = File(...),
    gps_lat: float | None = Form(default=None),
    gps_long: float | None = Form(default=None),
    timestamp: datetime | None = Form(default=None),
    node=Depends(get_node),
    db: Session = Depends(get_db),
) -> Observation:
    raw = await image.read()
    obs = observation_service.ingest_image(
        db, node, raw, image.filename, gps_lat, gps_long, timestamp
    )
    await broadcaster.broadcast("observation", _obs_json(obs))
    return obs


@router.post("/sensors", response_model=ObservationOut)
async def upload_sensors(
    req: SensorIn,
    node=Depends(get_node),
    db: Session = Depends(get_db),
) -> Observation:
    obs, _reading, raised = observation_service.ingest_sensors(
        db, node, req.temperature, req.humidity, req.soil_moisture,
        req.battery, req.timestamp,
    )
    await broadcaster.broadcast("observation", _obs_json(obs))
    for a in raised:
        await broadcaster.broadcast(
            "alert", AlertOut.model_validate(a).model_dump(mode="json")
        )
    return obs


@router.post("/heartbeat", response_model=NodeHealthOut)
async def heartbeat(
    req: HeartbeatIn,
    node=Depends(get_node),
    db: Session = Depends(get_db),
) -> NodeHealth:
    health = db.get(NodeHealth, node.id) or NodeHealth(node_id=node.id)
    health.status = "online"
    health.last_seen = _now()
    health.updated_at = _now()
    # Only overwrite fields the device actually reported.
    for field in ("battery", "wifi_strength", "firmware_version",
                  "gps_available", "camera_available", "storage_available"):
        val = getattr(req, field)
        if val is not None:
            setattr(health, field, val)
    db.add(health)
    db.add(NodeHeartbeat(
        node_id=node.id, source=req.source, battery=req.battery,
        wifi_strength=req.wifi_strength, firmware_version=req.firmware_version,
        gps_available=req.gps_available, camera_available=req.camera_available,
        storage_available=req.storage_available,
    ))
    raised = alerts.evaluate_battery(db, node.farm_id, node.id, req.battery)
    db.commit()
    db.refresh(health)

    payload = NodeHealthOut.model_validate(health).model_dump(mode="json")
    await broadcaster.broadcast("node_health", {"node_id": node.id, **payload})
    for a in raised:
        await broadcaster.broadcast(
            "alert", AlertOut.model_validate(a).model_dump(mode="json")
        )
    return health


@router.get("/status")
def node_status(node=Depends(get_node), db: Session = Depends(get_db)) -> dict:
    health = db.get(NodeHealth, node.id)
    open_alerts = list(db.execute(
        select(Alert).where(Alert.node_id == node.id, Alert.resolved.is_(False))
        .order_by(Alert.created_at.desc())
    ).scalars())
    return {
        "node_id": node.id,
        "farm_id": node.farm_id,
        "health": NodeHealthOut.model_validate(health).model_dump(mode="json") if health else None,
        "alerts": [AlertOut.model_validate(a).model_dump(mode="json") for a in open_alerts],
    }


@router.get("/history")
def node_history(
    limit: int = 50,
    node=Depends(get_node),
    db: Session = Depends(get_db),
) -> dict:
    observations = list(db.execute(
        select(Observation).where(Observation.node_id == node.id)
        .order_by(Observation.timestamp.desc()).limit(limit)
    ).scalars())
    readings = list(db.execute(
        select(SensorReading).where(SensorReading.node_id == node.id)
        .order_by(SensorReading.timestamp.desc()).limit(limit)
    ).scalars())
    return {
        "observations": [_obs_json(o) for o in observations],
        "readings": [SensorReadingOut.model_validate(r).model_dump(mode="json") for r in readings],
    }
