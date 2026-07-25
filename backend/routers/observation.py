"""Farmer-facing observation history. Ingest now lives in routers/node.py
(POST /node/image + /node/sensors), authenticated per node — there is no
anonymous observation upload.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.dependencies import get_current_farmer, owned_farm
from backend.models import Farmer, Observation
from backend.schemas import ObservationOut

router = APIRouter(prefix="/observations", tags=["observation"])


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
