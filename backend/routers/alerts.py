"""Farmer-facing alerts: list a farm's alerts and resolve one by hand.

Every route is scoped to the caller: a farm or alert that belongs to another
farmer is reported as not found, so its existence is not revealed.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.dependencies import get_current_farmer
from backend.models import Alert, Farm, Farmer
from backend.schemas import AlertOut
from backend.services import alerts

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(
    farm_id: int,
    include_resolved: bool = False,
    limit: int = 20,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> list[Alert]:
    farm = db.get(Farm, farm_id)
    if farm is None or farm.farmer_id != farmer.id:
        raise HTTPException(404, "Farm not found")
    q = select(Alert).where(Alert.farm_id == farm_id)
    if not include_resolved:
        q = q.where(Alert.resolved.is_(False))
    return list(db.execute(q.order_by(Alert.created_at.desc()).limit(limit)).scalars())


@router.post("/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(
    alert_id: int,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> Alert:
    alert = db.get(Alert, alert_id)
    farm = db.get(Farm, alert.farm_id) if alert else None
    if alert is None or farm is None or farm.farmer_id != farmer.id:
        raise HTTPException(404, "Alert not found")
    if not alert.resolved:
        alerts.resolve(alert, "manual")
        db.commit()
        db.refresh(alert)
    return alert
