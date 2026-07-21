"""Inspection session lifecycle."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Inspection, _now
from backend.realtime import broadcaster
from backend.schemas import InspectionOut

logger = logging.getLogger("gage.inspection")
router = APIRouter(prefix="/inspections", tags=["inspection"])


def active_inspection(db: Session) -> Inspection | None:
    return db.execute(
        select(Inspection).where(Inspection.ended_at.is_(None))
    ).scalars().first()


@router.post("/start", response_model=InspectionOut)
async def start_inspection(db: Session = Depends(get_db)) -> Inspection:
    if active_inspection(db):
        raise HTTPException(409, "An inspection is already active. Stop it first.")
    inspection = Inspection()
    db.add(inspection)
    db.commit()
    db.refresh(inspection)
    logger.info("inspection %d started", inspection.id)
    await broadcaster.broadcast("inspection", InspectionOut.model_validate(inspection).model_dump(mode="json"))
    return inspection


@router.post("/stop", response_model=InspectionOut)
async def stop_inspection(db: Session = Depends(get_db)) -> Inspection:
    inspection = active_inspection(db)
    if not inspection:
        raise HTTPException(404, "No active inspection.")
    inspection.ended_at = _now()
    db.commit()
    db.refresh(inspection)
    logger.info("inspection %d stopped (%d observations)", inspection.id, inspection.total_observations)
    await broadcaster.broadcast("inspection", InspectionOut.model_validate(inspection).model_dump(mode="json"))
    return inspection


@router.get("/current", response_model=InspectionOut | None)
def current_inspection(db: Session = Depends(get_db)) -> Inspection | None:
    return active_inspection(db)
