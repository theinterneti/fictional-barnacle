import pytest
import structlog


@pytest.fixture(autouse=True)
def clean_structlog() -> None:
    """Reset structlog to defaults before/after each test.

    Prevents configure_logging() calls in other test modules (e.g.
    test_s15_ac_compliance.py) from installing filter_by_level or
    stdlib.BoundLogger wrapper_class into the global processor chain,
    which would cause capture_logs() to miss events in CI.
    """
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()
