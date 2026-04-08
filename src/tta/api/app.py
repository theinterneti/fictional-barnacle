"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from tta import __version__
from tta.api.errors import (
    AppError,
    app_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from tta.api.health import router as health_router
from tta.api.middleware import RequestIDMiddleware
from tta.api.prometheus_middleware import PrometheusMiddleware
from tta.api.routes.games import router as games_router
from tta.api.routes.metrics import router as metrics_router
from tta.api.routes.players import router as players_router
from tta.logging import configure_logging

if TYPE_CHECKING:
    from tta.config import Settings

log = structlog.get_logger()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    # --- Startup ---

    # 0a. Langfuse LLM tracing (optional, graceful degradation)
    from tta.observability.langfuse import init_langfuse, shutdown_langfuse

    init_langfuse(settings)

    # 0b. OpenTelemetry tracing (before other services so spans are captured)
    from tta.observability.tracing import init_tracing, shutdown_tracing

    init_tracing(
        enabled=settings.otel_enabled,
        endpoint=settings.otel_endpoint,
    )

    # 1. Postgres engine + session factory
    from tta.persistence.engine import build_engine, build_session_factory

    engine = build_engine(
        settings.database_url,
        echo=(settings.environment == "development"),
    )
    session_factory = build_session_factory(engine)
    app.state.pg = session_factory
    app.state.pg_engine = engine

    # 2. Redis connection
    from redis.asyncio import Redis

    app.state.redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    # 2a. Turn result store (Redis-backed in prod, in-memory for tests)
    from tta.api.turn_results import (
        InMemoryTurnResultStore,
        RedisTurnResultStore,
    )

    if settings.llm_mock:
        app.state.turn_result_store = InMemoryTurnResultStore()
    else:
        app.state.turn_result_store = RedisTurnResultStore(app.state.redis)

    # 3. Prompt registry
    from tta.prompts.loader import FilePromptRegistry

    prompts_dir = Path(__file__).resolve().parents[3] / "prompts"
    app.state.prompt_registry = FilePromptRegistry(
        templates_dir=prompts_dir / "templates",
        fragments_dir=prompts_dir / "fragments",
    )

    # 4. LLM client
    if settings.llm_mock:
        from tta.llm.testing import MockLLMClient

        app.state.llm_client = MockLLMClient()
        log.info("llm_client_mock_enabled")
    else:
        from tta.llm.litellm_client import LiteLLMClient

        app.state.llm_client = LiteLLMClient()

    # 5. World service (in-memory for vertical slice, Neo4j later)
    from tta.world.memory_service import InMemoryWorldService

    app.state.world_service = InMemoryWorldService()

    # 6. Repository instances
    from tta.persistence.postgres import (
        PostgresSessionRepository,
        PostgresTurnRepository,
    )

    app.state.session_repo = PostgresSessionRepository(session_factory)
    app.state.turn_repo = PostgresTurnRepository(session_factory)

    # 7. Safety hooks (v1: passthrough)
    from tta.safety.hooks import PassthroughHook

    passthrough = PassthroughHook()

    # 8. Pipeline deps
    from tta.pipeline.types import PipelineDeps

    app.state.pipeline_deps = PipelineDeps(
        llm=app.state.llm_client,
        world=app.state.world_service,
        session_repo=app.state.session_repo,
        turn_repo=app.state.turn_repo,
        safety_pre_input=passthrough,
        safety_pre_gen=passthrough,
        safety_post_gen=passthrough,
        settings=settings,
    )

    # Redact credentials from DSN before logging
    from urllib.parse import urlparse

    _parsed = urlparse(settings.database_url)
    _safe_db = f"{_parsed.scheme}://{_parsed.hostname}:{_parsed.port}/{_parsed.path.lstrip('/')}"
    log.info(
        "app_startup_complete",
        database=_safe_db,
        redis=settings.redis_url,
    )

    yield

    # --- Shutdown ---
    shutdown_langfuse()
    shutdown_tracing()
    await app.state.redis.aclose()
    await engine.dispose()
    log.info("app_shutdown_complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return a fully configured FastAPI application.

    Parameters
    ----------
    settings:
        Optional pre-built Settings instance.  When *None* (the
        default, used by the uvicorn entrypoint), settings are
        loaded from environment variables via ``get_settings()``.
    """
    if settings is None:
        from tta.config import get_settings

        settings = get_settings()

    configure_logging(settings)

    app = FastAPI(
        title="Therapeutic Text Adventure",
        version=__version__,
        lifespan=_lifespan,
    )
    app.state.settings = settings

    # --- Exception handlers ---

    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)  # type: ignore[arg-type]

    # --- Middleware (added in reverse order — last added runs first) ---

    allow_credentials = "*" not in settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(PrometheusMiddleware)

    # --- Routers ---

    app.include_router(metrics_router)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(players_router, prefix="/api/v1")
    app.include_router(games_router, prefix="/api/v1")

    return app
