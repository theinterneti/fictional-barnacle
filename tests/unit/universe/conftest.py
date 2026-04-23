import pytest
import structlog

import tta.universe.composition as _comp_module


@pytest.fixture(autouse=True)
def _reset_structlog_for_universe() -> None:
    """Reset structlog and un-cache composition logger before each universe test.

    structlog.testing.capture_logs() uses in-place mutation of the current
    _CONFIG.default_processors list.  If a BoundLoggerLazyProxy was already
    cached (self.bind = finalized_bind) with an OLD list reference — because
    an earlier test called validate() before this one — then capture_logs()
    mutating the NEW list won't capture events from the cached logger.

    Fix:
      1. reset_defaults() creates a fresh _CONFIG.default_processors list.
      2. Deleting the cached 'bind' instance attribute forces the proxy to
         re-bind on its next call, which will be inside the capture_logs()
         block so it caches the correct [LogCapture] list.
    """
    structlog.reset_defaults()
    comp_log = getattr(_comp_module, "log", None)
    if comp_log is not None and "bind" in comp_log.__dict__:
        del comp_log.bind
    yield
    structlog.reset_defaults()
