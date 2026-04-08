"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

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
from tta.api.routes.games import router as games_router
from tta.api.routes.players import router as players_router
from tta.logging import configure_logging

if TYPE_CHECKING:
    from tta.config import Settings


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: future connection pools, caches, etc.
    yield
    # Shutdown: close connections, flush buffers, etc.


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

    # --- Routers ---

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(players_router, prefix="/api/v1")
    app.include_router(games_router, prefix="/api/v1")

    return app
