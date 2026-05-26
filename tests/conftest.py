"""Shared test fixtures."""

from __future__ import annotations

import re
import warnings

import pytest
from hypothesis import HealthCheck
from hypothesis import settings as h_settings

from tta.config import Settings
from tta.llm.testing import MockLLMClient

# ---------------------------------------------------------------------------
# @pytest.mark.spec AC ID format validation hook
# ---------------------------------------------------------------------------
_AC_CANONICAL = re.compile(r"^AC-\d{2}\.\d{2}$")


def pytest_collection_modifyitems(session, config, items: list[pytest.Item]) -> None:
    """Warn when @pytest.mark.spec carries a non-canonical AC ID (e.g., AC-7.1)."""
    for item in items:
        marker = item.get_closest_marker("spec")
        if marker is None:
            continue
        for ac_id in marker.args:
            if not _AC_CANONICAL.match(str(ac_id)):
                warnings.warn(
                    f"Non-canonical AC ID '{ac_id}' in {item.nodeid}. "
                    f"Expected AC-NN.NN (e.g., AC-10.01). "
                    f"Run `uv run python specs/trace_acs.py --validate` for details.",
                    UserWarning,
                    stacklevel=2,
                )


# ---------------------------------------------------------------------------
# Hypothesis profiles (S16 §10)
# ---------------------------------------------------------------------------
h_settings.register_profile(
    "dev", max_examples=10, suppress_health_check=[HealthCheck.too_slow]
)
h_settings.register_profile("default", max_examples=100)
h_settings.register_profile(
    "ci",
    max_examples=500,
    suppress_health_check=[HealthCheck.too_slow],
)
h_settings.load_profile("default")


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
    # Ports match docker-compose.test.yml (offset from dev to avoid conflicts).
    test_env = {
        "TTA_DATABASE_URL": "postgresql://tta_test:tta_test@localhost:5433/tta_test",
        "TTA_NEO4J_PASSWORD": "test_password",
        "TTA_NEO4J_URI": "bolt://localhost:7688",
        "TTA_REDIS_URL": "redis://localhost:6380/1",
        "TTA_ENVIRONMENT": "development",
        "TTA_LOG_LEVEL": "DEBUG",
        "TTA_LOG_FORMAT": "console",
    }
    for key, val in test_env.items():
        monkeypatch.setenv(key, val)
    return Settings()  # pyright: ignore[reportCallIssue] — monkeypatched env vars provide required args


@pytest.fixture()
def mock_llm_client() -> MockLLMClient:
    """Provide a deterministic ``MockLLMClient`` with a canned response."""
    return MockLLMClient()


# ---------------------------------------------------------------------------
# shared-langfuse mock mode (FB-005 / observability migration)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_shared_langfuse() -> None:
    """Configure shared-langfuse in mock mode for all tests.

    Suppresses OTEL exporter noise and initializes shared-langfuse with
    empty credentials so that ``is_configured()`` reports True (enabling
    the code paths) but ``llm_chat()`` uses deterministic mock responses.

    When shared-langfuse is not installed (e.g., CI without the local
    dependency), this is a silent no-op — observability code paths
    gracefully degrade via ``is_configured()`` returning False.
    """
    import os

    os.environ.setdefault("OTEL_TRACES_EXPORTER", "none")
    try:
        from shared_langfuse import init_langfuse

        init_langfuse(host="http://localhost:3001", public_key="pk-test", secret_key="sk-test")
    except ImportError:
        pass  # shared-langfuse not installed — observability gracefully degraded
