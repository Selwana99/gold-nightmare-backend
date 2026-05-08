"""Security — passcode verification + JWT cookies for owner sessions."""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)


# ─── Passcode verification (constant-time) ───

def verify_passcode(provided: str) -> bool:
    """Constant-time comparison against PERSONAL_PASSCODE."""
    expected = settings.PERSONAL_PASSCODE.encode("utf-8")
    actual = (provided or "").encode("utf-8")
    return secrets.compare_digest(expected, actual)


# ─── JWT helpers ───

def create_owner_token() -> str:
    """Issue a JWT for the owner session."""
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {
        "sub": "owner",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_owner_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("sub") != "owner":
            raise ValueError("Not an owner token")
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}") from e


def is_valid_token(token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        decode_owner_token(token)
        return True
    except ValueError:
        return False
