"""
Cache layer — Redis if REDIS_URL is set, otherwise an in-memory dict (no persistence).
Used for: rate limiting, price caching, analysis deduplication.
"""

import asyncio
import json
import logging
import time
from typing import Optional, Any

from app.config import settings

logger = logging.getLogger(__name__)


class _MemoryCache:
    """Simple in-memory cache with TTL (single-process only)."""

    def __init__(self):
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expires_at, value = item
            if expires_at < time.time():
                self._data.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> None:
        async with self._lock:
            self._data[key] = (time.time() + ttl_seconds, value)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def incr(self, key: str, ttl_seconds: int = 60) -> int:
        async with self._lock:
            cur = self._data.get(key)
            if not cur or cur[0] < time.time():
                self._data[key] = (time.time() + ttl_seconds, 1)
                return 1
            new_val = cur[1] + 1
            self._data[key] = (cur[0], new_val)
            return new_val


class _RedisCache:
    """Async Redis wrapper. Lazy-imports redis to avoid hard dependency."""

    def __init__(self, url: str):
        try:
            from redis.asyncio import Redis
        except ImportError as e:
            raise RuntimeError("redis package not installed") from e
        self._client = Redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Optional[Any]:
        raw = await self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> None:
        serialized = json.dumps(value) if not isinstance(value, str) else value
        await self._client.set(key, serialized, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def incr(self, key: str, ttl_seconds: int = 60) -> int:
        # Atomic increment with TTL on first set
        pipe = self._client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_seconds, nx=True)
        result = await pipe.execute()
        return int(result[0])


_cache: Optional[Any] = None


def get_cache():
    """Get the singleton cache instance."""
    global _cache
    if _cache is None:
        if settings.REDIS_URL:
            try:
                _cache = _RedisCache(settings.REDIS_URL)
                logger.info("Using Redis cache: %s", settings.REDIS_URL.split("@")[-1])
            except Exception as e:
                logger.warning("Redis unavailable, falling back to memory cache: %s", e)
                _cache = _MemoryCache()
        else:
            logger.info("Using in-memory cache (no REDIS_URL set)")
            _cache = _MemoryCache()
    return _cache
