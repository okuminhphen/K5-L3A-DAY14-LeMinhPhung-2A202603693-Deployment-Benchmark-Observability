"""Redis-backed sliding window rate limiter."""

import hashlib
import logging
import time
import uuid
import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("app.rate_limiter")
WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    """Enforce sliding-window rate limit per API key in Redis (raises 429)."""
    if r is None:
        return

    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    redis_key = f"ratelimit:{key_hash}"
    now = time.time()
    window_start = now - WINDOW_SECONDS

    try:
        r.zremrangebyscore(redis_key, 0, window_start)
        current_count = r.zcard(redis_key)
        if current_count >= settings.rate_limit_per_minute:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )
        member = f"{now}:{uuid.uuid4().hex[:8]}"
        pipe = r.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, WINDOW_SECONDS)
        pipe.execute()
    except HTTPException:
        raise
    except redis.RedisError as exc:
        logger.warning("redis_rate_limit_unavailable: %s", exc)
