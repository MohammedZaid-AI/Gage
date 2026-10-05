"""One-time migration: node API keys used to be stored in plaintext. Hash any
that still are, in place, with core.security.hash_node_key. Idempotent: keys
already hashed are left alone. Devices keep sending the same key; only what
the database holds changes."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.security import hash_node_key, is_hashed_node_key
from backend.models import Node

logger = logging.getLogger("gage.node_keys")


def hash_plaintext_keys(db: Session) -> list[str]:
    """Hash every plaintext node key. Returns the ids of nodes changed. Caller commits."""
    changed = []
    for node in db.execute(select(Node)).scalars():
        if not is_hashed_node_key(node.api_key):
            node.api_key = hash_node_key(node.api_key)
            changed.append(node.id)
    if changed:
        logger.info("hashed plaintext API keys for %d node(s): %s", len(changed), changed)
    return changed
