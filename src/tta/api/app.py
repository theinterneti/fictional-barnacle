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
from fastapi.responses import HTMLResponse

from tta import __version__
from tta.api.errors import (
    AppError,
    app_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from tta.api.health import router as health_router
from tta.api.middleware import (
    LatencyBudgetMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
)
from tta.api.prometheus_middleware import PrometheusMiddleware
from tta.api.routes.admin import router as admin_router
from tta.api.routes.auth import router as auth_router
from tta.api.routes.games import router as games_router
from tta.api.routes.metrics import router as metrics_router
from tta.api.routes.players import router as players_router
from tta.api.security_headers import SecurityHeadersMiddleware
from tta.logging import configure_logging

if TYPE_CHECKING:
    from tta.config import Settings
    from tta.moderation.recorder import ModerationRecorder

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
        pool_size=settings.pg_pool_min,
        max_overflow=settings.pg_pool_max - settings.pg_pool_min,
        pool_timeout=settings.pg_pool_timeout,
        pool_recycle=settings.pg_pool_idle_timeout,
        pool_pre_ping=True,
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

    # 2b. Rate limiter (Redis-backed, in-memory fallback — S25 §3)
    from tta.resilience.rate_limiter import (
        InMemoryRateLimiter,
        RedisRateLimiter,
    )

    try:
        await app.state.redis.ping()  # type: ignore[misc]
        app.state.rate_limiter = RedisRateLimiter(app.state.redis)
        log.info("rate_limiter_redis")
    except Exception:
        app.state.rate_limiter = InMemoryRateLimiter()
        log.warning("rate_limiter_fallback_inmemory")

    # 2c. Anti-abuse detector (Redis-backed, in-memory fallback — S25 §3.5)
    from tta.resilience.anti_abuse import (
        InMemoryAbuseDetector,
        RedisAbuseDetector,
    )

    if settings.anti_abuse_enabled:
        max_cd = settings.anti_abuse_max_cooldown
        try:
            await app.state.redis.ping()  # type: ignore[misc]
            app.state.abuse_detector = RedisAbuseDetector(
                app.state.redis,
                max_cooldown=max_cd,
            )
            log.info("abuse_detector_redis")
        except Exception:
            app.state.abuse_detector = InMemoryAbuseDetector(
                max_cooldown=max_cd,
            )
            log.warning("abuse_detector_fallback_inmemory")
    else:
        app.state.abuse_detector = None

    # 3. Prompt registry
    from tta.prompts.loader import FilePromptRegistry

    prompts_dir = Path(__file__).resolve().parents[3] / "prompts"
    app.state.prompt_registry = FilePromptRegistry(
        templates_dir=prompts_dir / "templates",
        fragments_dir=prompts_dir / "fragments",
    )
    # Fail-loud on missing or broken required templates (AC-09.1).
    app.state.prompt_registry.validate_required_templates()

    # 4. LLM client
    if settings.llm_mock:
        from tta.llm.testing import MockLLMClient

        app.state.llm_client = MockLLMClient()
        log.info("llm_client_mock_enabled")
    else:
        from tta.llm.litellm_client import LiteLLMClient

        app.state.llm_client = LiteLLMClient()

    # S17 FR-17.30: log configured LLM provider on startup for audit trail
    log.info(
        "llm_provider_configured",
        model=settings.litellm_model,
        fallback_model=settings.litellm_fallback_model or "none",
    )

    # 5. World service — Neo4j when explicitly configured, in-memory fallback
    app.state.neo4j_driver = None
    if settings.neo4j_uri:
        from neo4j import AsyncGraphDatabase

        from tta.world.neo4j_service import Neo4jWorldService

        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        try:
            await driver.verify_connectivity()
        except Exception:
            await driver.close()
            raise
        app.state.neo4j_driver = driver
        app.state.world_service = Neo4jWorldService(driver)
        _host = (
            settings.neo4j_uri.split("@")[-1]
            if "@" in settings.neo4j_uri
            else settings.neo4j_uri
        )
        log.info("world_service_neo4j", host=_host)
    else:
        from tta.world.memory_service import InMemoryWorldService

        app.state.world_service = InMemoryWorldService()
        log.info("world_service_in_memory")

    # 5b. Template registry — loads world templates for genesis
    from tta.world.template_registry import TemplateRegistry

    templates_dir = Path(__file__).resolve().parent.parent / "world" / "templates"
    app.state.template_registry = TemplateRegistry(templates_dir)
    log.info(
        "template_registry_loaded",
        count=len(app.state.template_registry.list_all()),
    )

    # 6. Repository instances
    from tta.persistence.postgres import (
        PostgresSessionRepository,
        PostgresTurnRepository,
    )

    app.state.session_repo = PostgresSessionRepository(session_factory)
    app.state.turn_repo = PostgresTurnRepository(session_factory)

    # 7. Safety / moderation hooks
    from tta.safety.hooks import PassthroughHook

    recorder: ModerationRecorder | None = None
    if settings.moderation_enabled:
        from tta.moderation.flagging import SessionFlagTracker
        from tta.moderation.hook import ModerationHook
        from tta.moderation.keyword_moderator import KeywordModerator
        from tta.moderation.recorder import ModerationRecorder

        moderator = KeywordModerator()
        fail_open = settings.moderation_fail_mode == "open"
        recorder = ModerationRecorder(session_factory)
        flag_tracker = SessionFlagTracker(
            threshold=settings.moderation_flag_threshold,
            window_minutes=settings.moderation_flag_window_minutes,
        )
        safety_hook = ModerationHook(
            moderator,
            enabled=True,
            fail_open=fail_open,
            recorder=recorder,
            flag_tracker=flag_tracker,
        )
    else:
        safety_hook = PassthroughHook()  # type: ignore[assignment]

    # Expose the hook on app.state so /health can check moderation status.
    app.state.moderation_hook = safety_hook

    # 7a. Moderation recorder on app.state for admin endpoints (S26 §3.5)
    app.state.moderation_recorder = recorder

    # 7b. Audit-log repository (S26 §3.7 — append-only)
    from tta.persistence.audit_repo import AuditLogRepository

    app.state.audit_repo = AuditLogRepository(session_factory)

    # 7c. LLM concurrency semaphore (S28 FR-28.11–13)
    from tta.llm.semaphore import LLMSemaphore

    app.state.llm_semaphore = LLMSemaphore(
        max_concurrent=settings.llm_max_concurrent,
        queue_size=settings.llm_queue_size,
        timeout=settings.llm_timeout,
    )

    # 8. Pipeline deps
    from tta.choices.consequence_service import InMemoryConsequenceService
    from tta.game.summary import ContextSummaryService
    from tta.pipeline.types import PipelineDeps
    from tta.resilience.circuit_breaker import LLM_BREAKER, CircuitBreaker
    from tta.world.relationship_service import InMemoryRelationshipService

    consequence_svc = InMemoryConsequenceService()
    app.state.summary_service = ContextSummaryService(model=settings.summary_model)
    relationship_svc = InMemoryRelationshipService()
    llm_circuit_breaker = CircuitBreaker(LLM_BREAKER)

    app.state.pipeline_deps = PipelineDeps(
        llm=app.state.llm_client,
        world=app.state.world_service,
        session_repo=app.state.session_repo,
        turn_repo=app.state.turn_repo,
        safety_pre_input=safety_hook,
        safety_pre_gen=safety_hook,
        safety_post_gen=safety_hook,
        settings=settings,
        consequence_service=consequence_svc,
        relationship_service=relationship_svc,
        prompt_registry=app.state.prompt_registry,
        llm_semaphore=app.state.llm_semaphore,
        llm_circuit_breaker=llm_circuit_breaker,
        db_session_factory=session_factory,
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

    # Start background loops
    import asyncio

    from tta.lifecycle.cleanup import lifecycle_loop
    from tta.privacy.purge import purge_loop

    purge_task = asyncio.create_task(purge_loop(session_factory, interval_seconds=3600))
    lifecycle_task = asyncio.create_task(
        lifecycle_loop(
            session_factory,
            interval_seconds=900,
            idle_timeout_minutes=settings.idle_timeout_minutes,
            anon_cleanup_days=settings.anon_cleanup_days,
        )
    )

    # Start pool metrics sampler (S28 FR-28.10)
    from tta.observability.pool_metrics import start_pool_metrics_sampler

    metrics_task = start_pool_metrics_sampler(app)

    # Start daily LLM cost summary task (S15 AC-31)
    from tta.observability.daily_cost import daily_cost_summary_loop

    daily_cost_task = asyncio.create_task(daily_cost_summary_loop())

    # Start Redis TTL compliance monitor (S12 AC-12.12)
    from tta.persistence.redis_health import ttl_monitor_loop

    ttl_monitor_task: asyncio.Task[None] | None = None
    if app.state.redis is not None:
        ttl_monitor_task = asyncio.create_task(ttl_monitor_loop(app.state.redis))

    yield

    # --- Shutdown ---
    if ttl_monitor_task is not None:
        ttl_monitor_task.cancel()
        try:
            await ttl_monitor_task
        except asyncio.CancelledError:
            pass
    daily_cost_task.cancel()
    try:
        await daily_cost_task
    except asyncio.CancelledError:
        pass
    metrics_task.cancel()
    try:
        await metrics_task
    except asyncio.CancelledError:
        pass
    lifecycle_task.cancel()
    try:
        await lifecycle_task
    except asyncio.CancelledError:
        pass
    purge_task.cancel()
    try:
        await purge_task
    except asyncio.CancelledError:
        pass
    shutdown_langfuse()
    shutdown_tracing()
    if app.state.neo4j_driver is not None:
        await app.state.neo4j_driver.close()
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
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
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
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "Last-Event-ID",
            "X-Request-ID",
            "X-Admin-Token",
        ],
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(LatencyBudgetMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(PrometheusMiddleware)

    # --- Routers ---

    app.include_router(metrics_router)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(players_router, prefix="/api/v1")
    app.include_router(games_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/admin")

    from tta.api.routes.disclaimer import router as disclaimer_router

    app.include_router(disclaimer_router, prefix="/api/v1")

    # --- Privacy policy (S17 FR-17.51) ---
    # Load once at startup to avoid blocking the event loop on every request.

    _privacy_md = Path(__file__).resolve().parents[3] / "docs" / "privacy-policy.md"
    try:
        _privacy_text = _privacy_md.read_text(encoding="utf-8")
    except FileNotFoundError:
        _privacy_text = "Privacy policy not found."
    _safe = (
        _privacy_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    _privacy_html = (
        "<!DOCTYPE html><html><head>"
        "<meta charset='utf-8'>"
        "<title>TTA Privacy Policy</title>"
        "<style>body{font-family:sans-serif;max-width:800px;"
        "margin:2em auto;padding:0 1em;line-height:1.6}"
        "pre{white-space:pre-wrap}</style>"
        "</head><body><pre>" + _safe + "</pre></body></html>"
    )

    @app.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
    async def privacy_policy() -> HTMLResponse:
        """Serve the privacy policy as a simple HTML page."""
        return HTMLResponse(content=_privacy_html)

    return app
