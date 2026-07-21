"""Observation intake: image + sensors -> stored, AI-described, broadcast."""
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai import describe_image
from backend.config import get_settings
from backend.database import get_db
from backend.models import Observation
from backend.realtime import broadcaster
from backend.routers.inspection import active_inspection
from backend.schemas import ObservationOut

logger = logging.getLogger("gage.observation")
router = APIRouter(prefix="/observations", tags=["observation"])

_IMAGE_DIR = Path(get_settings().image_dir)
_IMAGE_DIR.mkdir(parents=True, exist_ok=True)


@router.post("", response_model=ObservationOut)
async def create_observation(
    image: UploadFile | None = File(default=None),
    gps_lat: float | None = Form(default=None),
    gps_long: float | None = Form(default=None),
    temperature: float | None = Form(default=None),
    humidity: float | None = Form(default=None),
    soil_moisture: float | None = Form(default=None),
    timestamp: datetime | None = Form(default=None),
    db: Session = Depends(get_db),
) -> Observation:
    obs_id = uuid.uuid4().hex
    image_path: str | None = None
    ai_summary: str | None = None

    if image is not None:
        raw = await image.read()
        suffix = Path(image.filename or "").suffix or ".jpg"
        dest = _IMAGE_DIR / f"{obs_id}{suffix}"
        dest.write_bytes(raw)
        image_path = str(dest.as_posix())
        try:
            ai_summary = describe_image(raw)
        except Exception:  # never let a vision hiccup drop the observation
            logger.exception("vision analysis failed for %s", obs_id)
            ai_summary = "Automatic analysis unavailable."

    inspection = active_inspection(db)
    obs = Observation(
        id=obs_id,
        inspection_id=inspection.id if inspection else None,
        image_path=image_path,
        gps_lat=gps_lat,
        gps_long=gps_long,
        temperature=temperature,
        humidity=humidity,
        soil_moisture=soil_moisture,
        timestamp=timestamp or datetime.utcnow(),
        ai_summary=ai_summary,
    )
    db.add(obs)
    if inspection:
        inspection.total_observations += 1
    db.commit()
    db.refresh(obs)
    logger.info("observation %s stored (inspection=%s)", obs_id, obs.inspection_id)

    await broadcaster.broadcast(
        "observation", ObservationOut.model_validate(obs).model_dump(mode="json")
    )
    return obs


@router.get("", response_model=list[ObservationOut])
def list_observations(limit: int = 50, db: Session = Depends(get_db)) -> list[Observation]:
    return list(
        db.execute(
            select(Observation).order_by(Observation.timestamp.desc()).limit(limit)
        ).scalars()
    )
