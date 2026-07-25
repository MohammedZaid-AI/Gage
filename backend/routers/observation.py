"""Observation intake: a monitoring node posts image + sensors; we store it,
run vision analysis, and broadcast to live dashboards.

Node ingest is not farmer-authenticated in V1 — field devices can't carry a
farmer JWT. We validate that the node id resolves to a registered node and
derive the farm from it.
ponytail: add per-node API keys (X-Node-Key) in Phase 2 to authenticate devices.
"""
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai import describe_image
from backend.config import get_settings
from backend.database import get_db
from backend.dependencies import get_current_farmer, owned_farm
from backend.models import Farmer, Node, Observation, _now
from backend.realtime import broadcaster
from backend.schemas import ObservationOut

logger = logging.getLogger("gage.observation")
router = APIRouter(prefix="/observations", tags=["observation"])

_IMAGE_DIR = Path(get_settings().image_dir)
_IMAGE_DIR.mkdir(parents=True, exist_ok=True)


@router.post("", response_model=ObservationOut)
async def create_observation(
    node_id: str = Form(...),
    image: UploadFile | None = File(default=None),
    gps_lat: float | None = Form(default=None),
    gps_long: float | None = Form(default=None),
    temperature: float | None = Form(default=None),
    humidity: float | None = Form(default=None),
    soil_moisture: float | None = Form(default=None),
    timestamp: datetime | None = Form(default=None),
    db: Session = Depends(get_db),
) -> Observation:
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(404, "Unknown node")

    obs_id = uuid.uuid4().hex
    image_path: str | None = None
    vision_summary: str | None = None

    if image is not None:
        raw = await image.read()
        suffix = Path(image.filename or "").suffix or ".jpg"
        dest = _IMAGE_DIR / f"{obs_id}{suffix}"
        dest.write_bytes(raw)
        image_path = dest.as_posix()
        try:
            vision_summary = describe_image(raw)
        except Exception:  # never let a vision hiccup drop the observation
            logger.exception("vision analysis failed for %s", obs_id)
            vision_summary = "Automatic analysis unavailable."

    obs = Observation(
        id=obs_id,
        farm_id=node.farm_id,
        node_id=node.id,
        timestamp=timestamp or _now(),
        gps_lat=gps_lat,
        gps_long=gps_long,
        image_path=image_path,
        temperature=temperature,
        humidity=humidity,
        soil_moisture=soil_moisture,
        vision_summary=vision_summary,
    )
    node.last_seen = _now()
    node.status = "active"
    db.add(obs)
    db.commit()
    db.refresh(obs)
    logger.info("observation %s stored (node=%s farm=%s)", obs_id, node.id, node.farm_id)

    await broadcaster.broadcast(
        "observation", ObservationOut.model_validate(obs).model_dump(mode="json")
    )
    return obs


@router.get("/farms/{farm_id}", response_model=list[ObservationOut])
def list_observations(
    farm_id: int,
    limit: int = 50,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> list[Observation]:
    owned_farm(db, farmer, farm_id)
    return list(
        db.execute(
            select(Observation)
            .where(Observation.farm_id == farm_id)
            .order_by(Observation.timestamp.desc())
            .limit(limit)
        ).scalars()
    )
