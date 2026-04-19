"""Step definitions for rate_limiting.feature.

Tests that rate-limit headers are injected on successful requests and
that exceeding the limit returns a 429 with the S25 error envelope.
Shared given/then steps live in tests/bdd/conftest.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenario, then, when

from tests.bdd.conftest import (
    _GAME_ID,
    _game_row,
    _make_result,
)

FEATURE = "../features/api/rate_limiting.feature"


@scenario(FEATURE, "Successful requests include rate-limit headers")
def test_rate_limit_headers_present():
    pass


@scenario(FEATURE, "Exceeding the rate limit returns 429 with retry guidance")
def test_rate_limit_exceeded():
    pass


# ---- GIVEN ----


@given("rate limiting is enabled", target_fixture="ctx")
def rate_limiting_enabled(ctx: dict, app) -> dict:
    """Rate limiting is on by default (Settings.rate_limit_enabled=True).

    Use InMemoryRateLimiter with a fresh state so the middleware will inject
    X-RateLimit-* headers on allowed requests.
    """
    from tta.resilience.rate_limiter import InMemoryRateLimiter

    app.state.rate_limiter = InMemoryRateLimiter()
    ctx["rate_limiter"] = app.state.rate_limiter
    return ctx


@given("the player has exceeded the turn rate limit", target_fixture="ctx")
def rate_limit_exhausted(ctx: dict, app) -> dict:
    """Replace the limiter with one that always denies turn requests."""
    import time

    from tta.resilience.rate_limiter import InMemoryRateLimiter, RateLimitResult

    class _DenyAllLimiter(InMemoryRateLimiter):
        async def check(
            self, key: str, limit: int, window_seconds: int
        ) -> RateLimitResult:
            now = time.time()
            return RateLimitResult(
                allowed=False,
                limit=limit,
                remaining=0,
                reset_at=now + window_seconds,
                retry_after=60,
            )

    limiter = _DenyAllLimiter()
    ctx["rate_limiter"] = limiter
    app.state.rate_limiter = limiter
    return ctx


# ---- WHEN ----


def _setup_turn_pg(pg: AsyncMock) -> None:
    pg.execute = AsyncMock(
        side_effect=[
            _make_result(rows=[_game_row()]),  # _get_owned_game
            _make_result(),  # advisory lock
            _make_result(),  # in-flight check
            _make_result(scalar=0),  # max turn number
            _make_result(),  # INSERT turn
            _make_result(),  # UPDATE last_played_at
        ]
    )
    pg.commit = AsyncMock()


@when(
    parsers.parse('the player submits turn text "{text}"'),
    target_fixture="ctx",
)
def submit_turn(ctx: dict, client: TestClient, pg: AsyncMock, text: str) -> dict:
    _setup_turn_pg(pg)
    ctx["response"] = client.post(
        f"/api/v1/games/{_GAME_ID}/turns",
        json={"input": text},
    )
    return ctx


# ---- THEN ----


@then(parsers.parse('the response includes a "{header}" header'))
def response_has_header(ctx: dict, header: str) -> None:
    assert header in ctx["response"].headers, (
        f"Expected header {header!r} not found in {dict(ctx['response'].headers)}"
    )


@then(parsers.parse('the response error code is "{code}"'))
def response_error_code(ctx: dict, code: str) -> None:
    body = ctx["response"].json()
    assert "error" in body, f"Expected 'error' key in body: {body}"
    assert body["error"]["code"] == code, (
        f"Expected error code {code!r}, got {body['error']['code']!r}"
    )
