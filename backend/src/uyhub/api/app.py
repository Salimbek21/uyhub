"""FastAPI application.

Phase 0 serves liveness, readiness and metrics only. The ``/v1`` endpoints from
SPEC section 9 arrive in Phase 4.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from uyhub import __version__
from uyhub.api.routers import listings, meta
from uyhub.core.config import get_settings
from uyhub.core.db import check_database, dispose_engine
from uyhub.core.errors import DependencyUnavailableError
from uyhub.core.logging import configure_logging, get_logger
from uyhub.core.metrics import metrics_app
from uyhub.core.ratelimit import RateLimiter
from uyhub.core.redis import check_redis, close_redis, get_redis
from uyhub.core.s3 import check_s3

log = get_logger(__name__)

DependencyCheck = Callable[[], Awaitable[None]]

READINESS_CHECKS: dict[str, DependencyCheck] = {
    "postgres": check_database,
    "redis": check_redis,
    "s3": check_s3,
}


class HealthResponse(BaseModel):
    """Liveness payload — the process is up and serving."""

    status: Literal["ok"] = "ok"
    service: str = "api"
    version: str = __version__


class ReadinessResponse(BaseModel):
    """Readiness payload — every external dependency answered."""

    status: Literal["ready", "not_ready"]
    checks: dict[str, str]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info(
        "api.starting",
        app_env=settings.app_env,
        version=__version__,
        database=settings.safe_database_url,
        cors_origins=len(settings.cors_allow_origins),
        insecure_auth=settings.api_allow_insecure_auth,
    )
    if settings.api_allow_insecure_auth:
        # Loud, every start, for as long as it is on: this is the switch that
        # makes every caller a signed-in user (DECISIONS 4.5).
        log.warning("api.insecure_auth_enabled")
    if not settings.has_bot_token and not settings.api_allow_insecure_auth:
        log.warning("api.no_bot_token", detail="every authenticated request will be rejected")

    # One connection pool for the process, shared by every request.
    app.state.redis = get_redis(settings)
    app.state.rate_limiter = RateLimiter(
        app.state.redis,
        per_minute=settings.api_rate_limit_per_minute,
        burst=settings.api_rate_limit_burst,
    )

    yield
    await dispose_engine()
    await close_redis()
    log.info("api.stopped")


def create_app() -> FastAPI:
    """Build the ASGI application.

    Logging is configured here rather than only in the CLI: `uvicorn --reload` and
    any external ASGI server import this module in a worker process that never ran
    `uyhub api`, and that worker is the one serving requests. `configure_logging`
    is idempotent, so the CLI calling it first costs nothing.
    """
    settings = get_settings()
    configure_logging("api", level=settings.log_level, log_format=settings.log_format)
    app = FastAPI(
        title="UyHub API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )

    # SPEC 9.3: only the Mini App's origin. `allow_origins` is an exact list
    # and never `*` — the Mini App sends credentials, and a wildcard with
    # credentials is both refused by browsers and wrong to ask for.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    app.include_router(listings.router)
    app.include_router(meta.router)

    @app.get("/healthz", response_model=HealthResponse, tags=["ops"])
    async def healthz() -> HealthResponse:
        """Liveness. Touches no dependency so a restart loop stays diagnosable."""
        return HealthResponse()

    @app.get("/readyz", tags=["ops"])
    async def readyz() -> JSONResponse:
        """Readiness. Probes Postgres, Redis and object storage concurrently."""
        names = list(READINESS_CHECKS)
        results = await asyncio.gather(
            *(check() for check in READINESS_CHECKS.values()),
            return_exceptions=True,
        )

        checks: dict[str, str] = {}
        ready = True
        for name, result in zip(names, results, strict=True):
            if result is None:
                checks[name] = "ok"
            elif isinstance(result, DependencyUnavailableError):
                checks[name] = result.reason
                ready = False
            else:
                checks[name] = "error"
                ready = False

        if not ready:
            log.warning("api.not_ready", checks=checks)

        payload = ReadinessResponse(status="ready" if ready else "not_ready", checks=checks)
        return JSONResponse(
            status_code=200 if ready else 503,
            content=payload.model_dump(),
        )

    app.mount("/metrics", metrics_app())
    return app


app = create_app()
