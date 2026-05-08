"""Real-time gold (XAUUSD) price service. Uses GoldAPI primary, TwelveData fallback."""

import logging
import asyncio
from typing import Optional

import httpx

from app.config import settings
from app.core.cache import get_cache

logger = logging.getLogger(__name__)

CACHE_KEY = "price:xauusd"


async def _fetch_goldapi() -> Optional[float]:
    if not settings.GOLDAPI_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                "https://www.goldapi.io/api/XAU/USD",
                headers={"x-access-token": settings.GOLDAPI_KEY, "Content-Type": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
            return float(data.get("price", 0)) or None
    except Exception as e:
        logger.warning("GoldAPI failed: %s", e)
        return None


async def _fetch_twelvedata() -> Optional[float]:
    if not settings.TWELVEDATA_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                "https://api.twelvedata.com/price",
                params={"symbol": "XAU/USD", "apikey": settings.TWELVEDATA_KEY},
            )
            r.raise_for_status()
            data = r.json()
            return float(data.get("price", 0)) or None
    except Exception as e:
        logger.warning("TwelveData failed: %s", e)
        return None


async def get_current_gold_price() -> Optional[float]:
    """
    Returns current XAUUSD spot price, or None if unavailable.
    Cached for PRICE_CACHE_SECONDS to avoid burning API calls.
    """
    cache = get_cache()
    cached = await cache.get(CACHE_KEY)
    if cached is not None:
        try:
            return float(cached)
        except (TypeError, ValueError):
            pass

    price = await _fetch_goldapi()
    if price is None:
        price = await _fetch_twelvedata()

    if price:
        await cache.set(CACHE_KEY, price, ttl_seconds=settings.PRICE_CACHE_SECONDS)
        return price

    logger.info("No price source configured or available")
    return None
