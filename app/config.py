"""Application settings â€” single-user / personal."""

from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        case_sensitive=True, extra="ignore",
    )

    # â”€â”€â”€ App â”€â”€â”€
    APP_NAME: str = "Gold Nightmare Personal"
    APP_VERSION: str = "3.0.0"
    APP_ENV: str = "production"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    BASE_URL: str = "http://localhost:8000"

    # REQUIRED
    SECRET_KEY: str = "change-me-to-a-long-random-string-min-32-chars"

    # â”€â”€â”€ Server â”€â”€â”€
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # â”€â”€â”€ Owner identity â”€â”€â”€
    # Single passcode that grants access. Generate with: python -c "import secrets; print(secrets.token_urlsafe(16))"
    PERSONAL_PASSCODE: str = "change-me"
    # Optional Telegram user ID â€” bot will only respond to this user
    OWNER_TELEGRAM_ID: Optional[int] = None
    OWNER_DISPLAY_NAME: str = "Odai"

    # â”€â”€â”€ Anthropic (REQUIRED) â”€â”€â”€
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-opus-4-7"
    CLAUDE_MODEL_FAST: str = "claude-sonnet-4-6"
    MAX_OUTPUT_TOKENS: int = 4096

    # â”€â”€â”€ Database â”€â”€â”€
    DATABASE_URL: str = "sqlite+aiosqlite:///./gn_personal.db"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # â”€â”€â”€ Cache (optional) â”€â”€â”€
    REDIS_URL: Optional[str] = None
    CACHE_TTL_SECONDS: int = 3600

    # â”€â”€â”€ Telegram bot â”€â”€â”€
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_BOT_USERNAME: Optional[str] = None
    TELEGRAM_CHANNEL_ID: Optional[str] = None
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = None

    # â”€â”€â”€ Real-time gold price â”€â”€â”€
    GOLDAPI_KEY: Optional[str] = None
    TWELVEDATA_KEY: Optional[str] = None
    PRICE_CACHE_SECONDS: int = 30
    PRICE_CACHE_SECONDS: int = 30

    # â”€â”€â”€ Upload limits â”€â”€â”€
    MAX_UPLOAD_MB: int = 10
    MAX_IMAGES_PER_ANALYSIS: int = 4

    # â”€â”€â”€ Auth / JWT â”€â”€â”€
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 30  # 30 days

    # â”€â”€â”€ CORS â”€â”€â”€
    CORS_ORIGINS: str = "*"

    # â”€â”€â”€ Optional Sentry â”€â”€â”€
    SENTRY_DSN: Optional[str] = None

    # â”€â”€â”€ Feature flags â”€â”€â”€
    ENABLE_PDF_EXPORT: bool = True
    ENABLE_SHARE_LINKS: bool = True
    ENABLE_BACKGROUND_SCHEDULER: bool = True
    ENABLE_FEW_SHOT_LEARNING: bool = True
    ENABLE_ML_CLASSIFIER: bool = True
    ENABLE_AUTO_POST_CHANNEL: bool = False

    @property
    def cors_list(self) -> List[str]:
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
