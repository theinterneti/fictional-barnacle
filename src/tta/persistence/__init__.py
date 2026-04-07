"""Persistence layer — PostgreSQL, Neo4j, Redis."""

from tta.persistence.engine import build_engine, build_session_factory
from tta.persistence.memory import (
    InMemoryGameRepository,
    InMemoryPlayerRepository,
    InMemorySessionRepository,
    InMemoryTurnRepository,
    InMemoryWorldEventRepository,
)
from tta.persistence.postgres import (
    PostgresGameRepository,
    PostgresPlayerRepository,
    PostgresSessionRepository,
    PostgresTurnRepository,
    PostgresWorldEventRepository,
)

__all__ = [
    # Engine
    "build_engine",
    "build_session_factory",
    # Postgres repositories
    "PostgresGameRepository",
    "PostgresPlayerRepository",
    "PostgresSessionRepository",
    "PostgresTurnRepository",
    "PostgresWorldEventRepository",
    # In-memory repositories
    "InMemoryGameRepository",
    "InMemoryPlayerRepository",
    "InMemorySessionRepository",
    "InMemoryTurnRepository",
    "InMemoryWorldEventRepository",
]
