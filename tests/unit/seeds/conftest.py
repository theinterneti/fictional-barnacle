"""Seed-test configuration: wire structlog → stdlib so caplog captures records."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import structlog


@pytest.fixture(autouse=True)
def _structlog_stdlib(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Route structlog through stdlib logging so pytest caplog works."""
    original: dict[str, Any] = structlog.get_config()

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.KeyValueRenderer(key_order=["event"]),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    yield
    structlog.configure(**original)
