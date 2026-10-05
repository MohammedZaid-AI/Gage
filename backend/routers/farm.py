"""Farm and monitoring-node management (farmer-scoped)."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.security import generate_api_key, hash_node_key
from backend.database import get_db
from backend.dependencies import get_current_farmer, owned_farm
from backend.models import Farm, Farmer, Node
from backend.schemas import FarmCreate, FarmOut, NodeCreate, NodeOut

logger = logging.getLogger("gage.farm")
router = APIRouter(tags=["farm"])


@router.post("/farms", response_model=FarmOut, status_code=201)
def create_farm(
    req: FarmCreate,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> Farm:
    farm = Farm(farmer_id=farmer.id, **req.model_dump())
    db.add(farm)
    db.commit()
    db.refresh(farm)
    logger.info("farm %d created for farmer %d", farm.id, farmer.id)
    return farm


@router.get("/farms", response_model=list[FarmOut])
def list_farms(
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> list[Farm]:
    return list(
        db.execute(select(Farm).where(Farm.farmer_id == farmer.id)).scalars()
    )


@router.post("/farms/{farm_id}/nodes", response_model=NodeOut, status_code=201)
def register_node(
    farm_id: int,
    req: NodeCreate,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> NodeOut:
    farm = owned_farm(db, farmer, farm_id)
    if db.get(Node, req.id):
        raise HTTPException(409, "Node id already registered")
    raw_key = generate_api_key()
    node = Node(
        id=req.id, farm_id=farm.id, name=req.name,
        location=req.location, api_key=hash_node_key(raw_key),
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    logger.info("node %s registered on farm %d", node.id, farm.id)
    return _node_out(node, raw_key)   # the only time this key is ever shown


@router.get("/farms/{farm_id}/nodes", response_model=list[NodeOut])
def list_nodes(
    farm_id: int,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> list[NodeOut]:
    owned_farm(db, farmer, farm_id)
    nodes = db.execute(select(Node).where(Node.farm_id == farm_id)).scalars()
    return [_node_out(n) for n in nodes]   # keys are stored hashed; never listed


@router.post("/farms/{farm_id}/nodes/{node_id}/rotate-key", response_model=NodeOut)
def rotate_node_key(
    farm_id: int,
    node_id: str,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> NodeOut:
    """Issue a new key for a node (e.g. the old one was lost: stored keys are
    hashed and cannot be shown again). The old key stops working immediately."""
    owned_farm(db, farmer, farm_id)
    node = db.get(Node, node_id)
    if node is None or node.farm_id != farm_id:
        raise HTTPException(404, "Node not found")
    raw_key = generate_api_key()
    node.api_key = hash_node_key(raw_key)
    db.commit()
    db.refresh(node)
    logger.info("node %s key rotated", node.id)
    return _node_out(node, raw_key)


def _node_out(node: Node, raw_key: str | None = None) -> NodeOut:
    """Response for a node: the plain key only when it was just issued."""
    out = NodeOut.model_validate(node)
    return out.model_copy(update={"api_key": raw_key})
