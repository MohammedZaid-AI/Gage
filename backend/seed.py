"""Idempotent demo seed so the dashboard runs out of the box.

ponytail: demo-only. Delete once real farmer onboarding exists (Phase 4+).
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.security import hash_password
from backend.models import Farm, Farmer, Node

logger = logging.getLogger("gage.seed")

DEMO_PHONE = "9999999999"
DEMO_PASSWORD = "demo1234"
DEMO_NODE_ID = "demo-node-1"


def seed_demo(db: Session) -> None:
    if db.execute(select(Farmer).where(Farmer.phone == DEMO_PHONE)).scalar_one_or_none():
        return
    farmer = Farmer(
        phone=DEMO_PHONE,
        password_hash=hash_password(DEMO_PASSWORD),
        name="Demo Farmer",
        language="kn",
    )
    db.add(farmer)
    db.flush()
    farm = Farm(farmer_id=farmer.id, name="Demo Farm", village="Mandya", area_acres=2.5)
    db.add(farm)
    db.flush()
    db.add(Node(id=DEMO_NODE_ID, farm_id=farm.id, name="Field node 1"))
    db.commit()
    logger.info("seeded demo farmer/farm/node (phone=%s)", DEMO_PHONE)
