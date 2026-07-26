"""Dataset API. Thin: resolves the farmer's farms and delegates to the Dataset
Builder services. All dataset logic lives in backend/dataset/*.

Endpoints are farmer-scoped (a farmer sees/exports their own farms' data).
Conversation links are refreshed lazily here so reads/exports reflect them.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.dataset.exporter import Exporter
from backend.dataset.repository import DatasetFilters, DatasetRepository
from backend.dataset.schemas import DatasetEntryOut, ExportOut, ExportRequest
from backend.dataset.service import DatasetService
from backend.dependencies import get_current_farmer
from backend.models import Farm, Farmer

router = APIRouter(prefix="/dataset", tags=["dataset"])


def _farm_ids(db: Session, farmer: Farmer) -> list[int]:
    return list(db.execute(
        select(Farm.id).where(Farm.farmer_id == farmer.id)
    ).scalars())


def _refresh_links(db: Session, farm_ids: list[int]) -> None:
    for fid in farm_ids:
        DatasetService.link_recent_conversations(db, fid)


@router.get("", response_model=list[DatasetEntryOut])
def list_entries(
    crop_type: str | None = None,
    min_quality: int | None = None,
    status: str | None = None,
    limit: int = 100,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
):
    farm_ids = _farm_ids(db, farmer)
    _refresh_links(db, farm_ids)
    f = DatasetFilters(crop_type=crop_type, min_quality=min_quality, status=status)
    return DatasetRepository.list(db, farm_ids, f, limit=limit)


@router.get("/stats")
def stats(
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> dict:
    farm_ids = _farm_ids(db, farmer)
    _refresh_links(db, farm_ids)
    return DatasetRepository.stats(db, farm_ids)


@router.post("/export", response_model=ExportOut)
def export(
    req: ExportRequest,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
):
    farm_ids = _farm_ids(db, farmer)
    _refresh_links(db, farm_ids)
    f = DatasetFilters(
        farm_id=req.farm_id, crop_type=req.crop_type, min_quality=req.min_quality,
        status=req.status, date_from=req.date_from, date_to=req.date_to,
    )
    try:
        return Exporter.export(db, farm_ids, f, req.fmt)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/{entry_id}", response_model=DatasetEntryOut)
def get_entry(
    entry_id: int,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
):
    entry = DatasetRepository.get(db, entry_id)
    if entry is None or entry.farm_id not in _farm_ids(db, farmer):
        raise HTTPException(404, "Dataset entry not found")
    return entry
