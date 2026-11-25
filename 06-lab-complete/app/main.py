"""Production AI Agent — Part 6 Final Project."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import signal
import sys
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging() -> logging.Logger:
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False
    if not app_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        app_logger.addHandler(handler)
    return app_logger


logger = _configure_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Manage startup and graceful shutdown lifecycle."""
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def _on_sigterm(signum, frame):
        logger.info("sigterm_received")
        if callable(previous_sigterm):
            previous_sigterm(signum, frame)

    signal.signal(signal.SIGTERM, _on_sigterm)
    logger.info(
        json.dumps(
            {
                "event": "startup",
                "environment": settings.environment,
                "port": settings.port,
            }
        )
    )
    yield
    logger.info(json.dumps({"event": "shutdown_complete"}))


app = FastAPI(
    title="Production AI Agent",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    """Return a clean JSON 500 response without leaking stack traces."""
    logger.error("unhandled_error: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    """Request schema for POST /ask."""

    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None


@app.get("/health")
def health():
    """Liveness probe — always returns 200 while the process is alive."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness probe — returns 200 when Redis is reachable, 503 otherwise."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not available")
    return {"status": "ready"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    """Protected agent endpoint with auth, rate limiting, and cost guard."""
    started = time.perf_counter()
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question.split()) * 2)
    output_tokens = max(1, len(answer.split()) * 2)
    cost_usd = record_cost(input_tokens, output_tokens)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        json.dumps(
            {
                "event": "request",
                "path": "/ask",
                "status": 200,
                "ms": elapsed_ms,
                "cost_usd": round(cost_usd, 6),
            }
        )
    )
    return {
        "question": body.question,
        "answer": answer,
        "user_id": body.user_id,
    }
