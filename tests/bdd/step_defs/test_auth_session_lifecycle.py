"""BDD step definitions for S11 session lifecycle scenarios.

Covers:
- FR-11.20/21: refresh token rotation
- FR-11.22 / AC-11.10: reuse detection → session revocation
- FR-11.23: logout
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenario, then, when

from tests.bdd.conftest import _make_result

FEATURE = "../features/auth/session_lifecycle.feature"

# Fixed IDs reused across steps within a scenario
_PLAYER_ID = str(uuid4())
_SESSION_ID = str(uuid4())
_JTI = str(uuid4())
_USED_JTI = str(uuid4())
_USED_SESSION_ID = str(uuid4())


# ── Scenarios ───────────────────────────────────────────────────────────────


@scenario(FEATURE, "Valid refresh token rotation issues new credentials")
def test_refresh_rotation() -> None:
    pass


@scenario(FEATURE, "Reused refresh token triggers session revocation")
def test_reuse_revokes_session() -> None:
    pass


@scenario(FEATURE, "Player logout succeeds and clears the session")
def test_logout_success() -> None:
    pass


@scenario(FEATURE, "Refresh token is rejected as an access credential at logout")
def test_logout_type_confusion() -> None:
    pass


# ── Given ───────────────────────────────────────────────────────────────────


@given(
    "a player has registered anonymously and holds a refresh token",
    target_fixture="ctx",
)
def player_holds_refresh_token(ctx: dict, pg: AsyncMock) -> dict:
    """Set up the 6-query happy-path pg side_effect for refresh."""
    token_row_id = str(uuid4())
    mark_result = MagicMock()
    mark_result.rowcount = 1

    pg.execute = AsyncMock(
        side_effect=[
            # 1. SELECT id, used FROM refresh_tokens WHERE token_jti=:jti
            _make_result(rows=[{"id": token_row_id, "used": False}]),
            # 2. SELECT is_anonymous, revoked_at FROM auth_sessions WHERE id=:sid
            _make_result(rows=[{"is_anonymous": True, "revoked_at": None}]),
            # 3. SELECT role, is_anonymous FROM players WHERE id=:id
            _make_result(rows=[{"role": "player", "is_anonymous": True}]),
            # 4. UPDATE refresh_tokens SET used=true WHERE id=:id AND used=false
            mark_result,
            # 5. INSERT INTO refresh_tokens
            _make_result(),
            # 6. UPDATE auth_sessions SET last_used_at=:now WHERE id=:sid
            _make_result(),
        ]
    )
    pg.commit = AsyncMock()
    ctx.update(
        jti=_JTI,
        sfid=_SESSION_ID,
        player_id=_PLAYER_ID,
        refresh_token="valid_refresh_token",
    )
    return ctx


@given("a player has an already-used refresh token", target_fixture="ctx")
def player_has_used_token(ctx: dict, pg: AsyncMock) -> dict:
    """Set up the 2-query reuse-detection pg side_effect."""
    pg.execute = AsyncMock(
        side_effect=[
            # 1. SELECT id, used FROM refresh_tokens WHERE token_jti=:jti → used=True
            _make_result(rows=[{"id": str(uuid4()), "used": True}]),
            # 2. UPDATE auth_sessions SET revoked_at=:now WHERE id=:sid
            _make_result(),
        ]
    )
    pg.commit = AsyncMock()
    ctx.update(
        jti=_USED_JTI,
        sfid=_USED_SESSION_ID,
        player_id=_PLAYER_ID,
        refresh_token="reused_refresh_token",
    )
    return ctx


@given("a player has a valid access token for logout", target_fixture="ctx")
def player_has_access_token(ctx: dict, pg: AsyncMock) -> dict:
    """Set up the 1-query logout pg side_effect."""
    pg.execute = AsyncMock(return_value=_make_result())
    pg.commit = AsyncMock()
    ctx.update(
        jti=_JTI,
        sfid=_SESSION_ID,
        access_token="valid_access_token",
        token_error=False,
    )
    return ctx


@given("a player presents a refresh token for logout", target_fixture="ctx")
def player_uses_refresh_for_logout(ctx: dict, pg: AsyncMock) -> dict:
    """No pg calls — decode_token will raise before any DB access."""
    ctx.update(
        access_token="refresh_token_used_by_mistake",
        token_error=True,
    )
    return ctx


# ── When ────────────────────────────────────────────────────────────────────


@when("the player exchanges their refresh token", target_fixture="ctx")
def exchange_refresh_token(ctx: dict, unauth_client: TestClient) -> dict:
    with (
        patch("tta.api.routes.auth.decode_token") as mock_decode,
        patch(
            "tta.api.routes.auth.is_token_denied", new_callable=AsyncMock
        ) as mock_denied,
        patch("tta.api.routes.auth.create_access_token") as mock_create_access,
        patch("tta.api.routes.auth.create_refresh_token") as mock_create_refresh,
    ):
        mock_decode.return_value = {
            "jti": ctx["jti"],
            "sub": ctx["player_id"],
            "sfid": ctx["sfid"],
            "typ": "refresh",
        }
        mock_denied.return_value = False
        mock_create_access.return_value = "new_access_tok"
        mock_create_refresh.return_value = ("new_refresh_tok", "new_jti_hex")
        ctx["response"] = unauth_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": ctx["refresh_token"]},
        )
    return ctx


@when("the player calls the logout endpoint", target_fixture="ctx")
def call_logout(ctx: dict, unauth_client: TestClient) -> dict:
    from tta.auth.jwt import TokenError

    with patch("tta.api.routes.auth.decode_token") as mock_decode:
        if ctx.get("token_error"):
            mock_decode.side_effect = TokenError("wrong type")
        else:
            mock_decode.return_value = {
                "jti": ctx["jti"],
                "sub": _PLAYER_ID,
                "sfid": ctx["sfid"],
                "typ": "access",
                "exp": int(time.time()) + 3600,
            }
        ctx["response"] = unauth_client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {ctx['access_token']}"},
        )
    return ctx


# ── Then ────────────────────────────────────────────────────────────────────


@then("the response contains a new access token and refresh token")
def check_new_token_pair(ctx: dict) -> None:
    data = ctx["response"].json()["data"]
    assert data["access_token"] == "new_access_tok"
    assert data["refresh_token"] == "new_refresh_tok"


@then(parsers.parse('the error code is "{code}"'))
def check_error_code(ctx: dict, code: str) -> None:
    body = ctx["response"].json()
    assert body["error"]["code"] == code
