"""Auth dependency: extracts owner JWT from cookie or Authorization header."""

import logging
from typing import Optional

from fastapi import HTTPException, Request, status

from app.core.security import decode_owner_token

logger = logging.getLogger(__name__)


async def require_owner(request: Request) -> str:
    """
    Verify that the request carries a valid owner JWT.
    Returns "owner" string on success, raises 401 otherwise.
    """
    # Try Authorization header first
    token: Optional[str] = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()

    # Fallback to cookie
    if not token:
        token = request.cookies.get("gn_session")

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
