"""Password hashing (bcrypt) and JWT access tokens. Pure crypto, no DB access."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from backend.config import get_settings

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
