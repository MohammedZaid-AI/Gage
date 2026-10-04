"""Password hashing (bcrypt), JWT access tokens, node API keys. Pure crypto, no DB."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from backend.config import get_settings


def generate_api_key() -> str:
    """A new random per-node API key (192 bits). Shown to the farmer once; only
    its hash (hash_node_key) is stored."""
    return secrets.token_urlsafe(24)


NODE_KEY_PREFIX = "hmac-sha256$"


def _node_key_secret() -> bytes:
    s = get_settings()
    return (s.node_key_secret or f"gage-node-key-v1:{s.jwt_secret}").encode()


def hash_node_key(raw_key: str) -> str:
    """What is stored for a node API key: HMAC-SHA256 under a server secret.
    Deterministic, so a device's key can be looked up by its hash; useless to
    anyone who reads the database without the secret."""
    digest = hmac.new(_node_key_secret(), raw_key.encode(), hashlib.sha256).hexdigest()
    return NODE_KEY_PREFIX + digest


def is_hashed_node_key(stored: str) -> bool:
    return stored.startswith(NODE_KEY_PREFIX)

# bcrypt hashes at most 72 bytes; longer passwords are silently truncated by the
# algorithm, so we slice explicitly to keep hashing and verifying consistent.
_MAX = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:_MAX], bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:_MAX], password_hash.encode())
    except ValueError:  # malformed hash
        return False


def create_access_token(farmer_id: int) -> str:
    s = get_settings()
    payload = {
        "sub": str(farmer_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=s.jwt_expire_minutes),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> int | None:
    """Return the farmer id encoded in the token, or None if invalid/expired."""
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
