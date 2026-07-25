"""Farm and monitoring-node management (farmer-scoped)."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

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
) -> Node:
    farm = owned_farm(db, farmer, farm_id)
    if db.get(Node, req.id):
        raise HTTPException(409, "Node id already registered")
    node = Node(id=req.id, farm_id=farm.id, name=req.name)
    db.add(node)
    db.commit()
    db.refresh(node)
    logger.info("node %s registered on farm %d", node.id, farm.id)
    return node


@router.get("/farms/{farm_id}/nodes", response_model=list[NodeOut])
def list_nodes(
    farm_id: int,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> list[Node]:
    owned_farm(db, farmer, farm_id)
    return list(db.execute(select(Node).where(Node.farm_id == farm_id)).scalars())
