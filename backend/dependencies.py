"""Shared FastAPI dependencies: current farmer + farm-ownership enforcement."""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.core.security import decode_access_token
from backend.database import get_db
from backend.models import Farm, Farmer

_bearer = HTTPBearer(auto_error=True)


def get_current_farmer(
    cred: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Farmer:
    farmer_id = decode_access_token(cred.credentials)
    if farmer_id is None:
        raise HTTPException(401, "Invalid or expired token")
    farmer = db.get(Farmer, farmer_id)
    if farmer is None:
        raise HTTPException(401, "Farmer not found")
    return farmer


def owned_farm(db: Session, farmer: Farmer, farm_id: int) -> Farm:
    """Load a farm and assert the farmer owns it. 404 if missing, 403 if not theirs."""
    farm = db.get(Farm, farm_id)
    if farm is None:
        raise HTTPException(404, "Farm not found")
    if farm.farmer_id != farmer.id:
        raise HTTPException(403, "Not your farm")
    return farm
