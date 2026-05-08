"""Auth endpoints — passcode login → JWT cookie."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, Request

from app.api.deps import require_owner
from app.config import settings
from app.core.security import verify_passcode, create_owner_token
from app.schemas.auth import PasscodeLogin, TokenResponse, OwnerInfo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: PasscodeLogin, response: Response, request: Request):
    """
    Login with the personal passcode.
    Sets `gn_session` HTTP-only cookie and returns the bearer token.
    """
    if not verify_passcode(body.passcode):
        # Don't leak timing info: same response shape but 401
        logger.warning("Failed passcode attempt from %s", request.client.host if request.client else "?")
        raise HTTPException(401, "كلمة المرور غير صحيحة")

    token = create_owner_token()

    # Set HTTP-only cookie
    is_secure = request.url.scheme == "https" or settings.APP_ENV == "production"
    response.set_cookie(
        key="gn_session",
        value=token,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=settings.JWT_EXPIRE_MINUTES * 60,
        path="/",
    )

    logger.info("Owner logged in")
    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.JWT_EXPIRE_MINUTES,
    )


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="gn_session", path="/")
    return {"ok": True}


@router.get("/me", response_model=OwnerInfo)
async def me(_: Annotated[str, Depends(require_owner)]):
    """Return basic owner info (only for authenticated session)."""
    return OwnerInfo(
        display_name=settings.OWNER_DISPLAY_NAME,
        has_telegram=bool(settings.TELEGRAM_BOT_TOKEN and settings.OWNER_TELEGRAM_ID),
        bot_username=settings.TELEGRAM_BOT_USERNAME,
    )
