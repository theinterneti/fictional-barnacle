"""Shared test fixtures."""

from __future__ import annotations

import pytest

from tta.config import Settings
from tta.llm.testing import MockLLMClient


@pytest.fixture()
def anyio_backend() -> str:
    """Force asyncio as the async backend for anyio-based tests."""
    return "asyncio"


@pytest.fixture()
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Return a ``Settings`` instance wired to test-safe defaults.

    Sets environment variables so that ``Settings()`` can be instantiated
    without real database connections being available.
    """
    test_env = {
        "TTA_DATABASE_URL": "postgresql://test:test@localhost:5432/tta_test",
        "TTA_NEO4J_PASSWORD": "test",
        "TTA_NEO4J_URI": "bolt://localhost:7687",
        "TTA_REDIS_URL": "redis://localhost:6379/1",
        "TTA_ENVIRONMENT": "development",
        "TTA_LOG_LEVEL": "DEBUG",
        "TTA_LOG_FORMAT": "console",
    }
    for key, val in test_env.items():
        monkeypatch.setenv(key, val)
    return Settings()


@pytest.fixture()
def mock_llm_client() -> MockLLMClient:
    """Provide a deterministic ``MockLLMClient`` with a canned response."""
    return MockLLMClient()
