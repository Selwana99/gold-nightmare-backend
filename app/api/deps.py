"""Auth dependencies for owner and mobile app sessions."""

import logging
from typing import Optional

from fastapi import HTTPException, Request, status

from app.core.security import decode_app_token, decode_owner_token

logger = logging.getLogger(__name__)


def _extract_token(request: Request) -> Optional[str]:
    token: Optional[str] = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    if not token:
        token = request.cookies.get("gn_session")
    return token


async def require_owner(request: Request) -> str:
    """Require an owner JWT."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="غير مصرّح — قم بتسجيل الدخول",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        decode_owner_token(token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="جلسة منتهية أو غير صالحة",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return "owner"


async def require_app_access(request: Request) -> dict:
    """Allow owner or active subscriber JWTs to use app APIs."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="غير مصرّح — قم بتسجيل الدخول",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_app_token(token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="جلسة منتهية أو غير صالحة",
            headers={"WWW-Authenticate": "Bearer"},
        )
