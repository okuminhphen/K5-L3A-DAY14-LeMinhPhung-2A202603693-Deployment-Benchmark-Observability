"""Shared Redis client and health check helper."""

import redis
from app.config import settings


def _create_client() -> redis.Redis | None:
    """Create a lazy Redis client without connecting at import time."""
    if not settings.redis_url:
        return None
    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )


r: redis.Redis | None = _create_client()


def redis_healthy() -> bool:
    """Return True if Redis responds to PING, False otherwise."""
    if r is None:
        return False
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
