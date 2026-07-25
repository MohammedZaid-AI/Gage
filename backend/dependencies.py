"""Shared FastAPI dependencies: current farmer, farm-ownership, and node auth."""
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.security import decode_access_token
from backend.database import get_db
from backend.models import Farm, Farmer, Node

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


def get_node(
    x_node_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Node:
    """Authenticate a monitoring node by its API key. Never allow anonymous uploads."""
    if not x_node_key:
        raise HTTPException(401, "Missing X-Node-Key header")
    node = db.execute(select(Node).where(Node.api_key == x_node_key)).scalar_one_or_none()
    if node is None:
        raise HTTPException(401, "Invalid node API key")
    return node
