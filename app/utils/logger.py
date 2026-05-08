"""Structured logging setup."""

import logging
import sys

from app.config import settings


def setup_logging() -> None:
    """Configure root logger with consistent format."""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Remove existing handlers
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    fmt = "%(asctime)s [%(levelname).1s] %(name)s: %(message)s"
    if settings.APP_ENV == "production":
        fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet noisy libs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)
