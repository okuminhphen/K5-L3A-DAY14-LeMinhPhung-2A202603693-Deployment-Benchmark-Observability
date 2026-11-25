"""Redis-backed daily LLM cost guard."""

import logging
from datetime import datetime, timezone
import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("app.cost_guard")

PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006
COST_KEY_TTL_SECONDS = 48 * 3600


def _daily_cost_key() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"cost:daily:{today}"


def check_budget() -> None:
    """Check accumulated daily spend in Redis before calling LLM (raises 402)."""
    if r is None:
        return

    try:
        raw = r.get(_daily_cost_key())
        spent = float(raw) if raw is not None else 0.0
    except (redis.RedisError, ValueError) as exc:
        logger.warning("redis_cost_check_unavailable: %s", exc)
        return

    if spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail="Daily budget exceeded",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Calculate token cost and atomically increment daily spend in Redis."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    if r is None:
        return cost

    key = _daily_cost_key()
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(key, cost)
        pipe.expire(key, COST_KEY_TTL_SECONDS)
        pipe.execute()
    except redis.RedisError as exc:
        logger.warning("redis_cost_record_unavailable: %s", exc)
    return cost
