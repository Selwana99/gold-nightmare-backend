"""Auth schemas — single passcode login."""

from typing import Optional
from pydantic import BaseModel, Field


class PasscodeLogin(BaseModel):
    passcode: str = Field(..., min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class OwnerInfo(BaseModel):
    display_name: str
    has_telegram: bool
    bot_username: Optional[str] = None
