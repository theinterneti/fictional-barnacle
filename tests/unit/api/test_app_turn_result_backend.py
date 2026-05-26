"""Tests for FastAPI app backend selection."""

from __future__ import annotations

from typing import Any

from tta.api.app import _resolve_turn_result_backend
from tta.config import Settings


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://user:pass@localhost:5432/tta_test",
        "redis_url": "redis://localhost:6379/0",
        "neo4j_uri": "bolt://localhost:7687",
        "neo4j_user": "neo4j",
        "neo4j_password": "test-password",
        "openai_api_key": "test-key",
    }
    values.update(overrides)
    return Settings(**values)


def test_auto_turn_result_backend_uses_memory_for_mock_llm() -> None:
    settings = _settings(llm_mock=True, turn_result_backend="auto")

    assert _resolve_turn_result_backend(settings) == "memory"


def test_auto_turn_result_backend_uses_redis_for_non_mock_llm() -> None:
    settings = _settings(llm_mock=False, turn_result_backend="auto")

    assert _resolve_turn_result_backend(settings) == "redis"


def test_explicit_turn_result_backend_overrides_mock_default() -> None:
    settings = _settings(llm_mock=True, turn_result_backend="redis")

    assert _resolve_turn_result_backend(settings) == "redis"
