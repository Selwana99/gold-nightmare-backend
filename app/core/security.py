"""Security helpers: passcode verification and JWT sessions."""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)


# Passcode verification

def verify_passcode(provided: str) -> bool:
    """Constant-time comparison against PERSONAL_PASSCODE."""
    expected = settings.PERSONAL_PASSCODE.encode("utf-8")
    actual = (provided or "").encode("utf-8")
    return secrets.compare_digest(expected, actual)


# JWT helpers

def _encode_session(payload: dict) -> str:
    payload = {
        **payload,
        "exp": datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_owner_token() -> str:
    """Issue a JWT for the owner session."""
    return _encode_session({"sub": "owner", "role": "owner"})


def create_subscriber_token(username: str, device_id: str) -> str:
    """Issue a JWT for an active subscriber locked to one device."""
    return _encode_session({
        "sub": f"subscriber:{username}",
        "role": "subscriber",
        "telegram_username": username,
        "device_id": device_id,
    })


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}") from e


def decode_owner_token(token: str) -> dict:
    payload = decode_token(token)
    if payload.get("sub") != "owner" or payload.get("role") != "owner":
        raise ValueError("Not an owner token")
    return payload


def decode_app_token(token: str) -> dict:
    payload = decode_token(token)
    role = payload.get("role")
    if role not in {"owner", "subscriber"}:
        raise ValueError("Not an app token")
    return payload


def is_valid_token(token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        decode_app_token(token)
        return True
    except ValueError:
        return False
