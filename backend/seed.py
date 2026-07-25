"""Idempotent demo seed so the dashboard runs out of the box.

ponytail: demo-only. Delete once real farmer onboarding exists (Phase 4+).
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.security import hash_password
from backend.models import Farm, Farmer, Node, NodeHealth, _now

logger = logging.getLogger("gage.seed")

DEMO_PHONE = "9999999999"
DEMO_PASSWORD = "demo1234"
DEMO_NODE_ID = "demo-node-1"
DEMO_NODE_KEY = "demo-node-key-123"  # fixed so the dashboard/tests can use it


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
    farm = Farm(farmer_id=farmer.id, name="Demo Farm", crop_type="sugarcane",
                village="Mandya", area_acres=2.5)
    db.add(farm)
    db.flush()
    db.add(Node(
        id=DEMO_NODE_ID, farm_id=farm.id, name="Field node 1",
        api_key=DEMO_NODE_KEY, location="North plot",
    ))
    db.add(NodeHealth(
        node_id=DEMO_NODE_ID, status="online", last_seen=_now(),
        battery=100.0, wifi_strength=-55, firmware_version="1.0.0",
    ))
    db.commit()
    logger.info("seeded demo farmer/farm/node (phone=%s, node_key=%s)",
                DEMO_PHONE, DEMO_NODE_KEY)
