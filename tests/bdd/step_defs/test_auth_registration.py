"""BDD step definitions for S11 anonymous registration scenarios.

Covers:
- FR-11.10: anonymous identity provisioning
- AC-11.12: no credential data in response
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pytest_bdd import scenario, then, when

from tests.bdd.conftest import _make_result

FEATURE = "../features/auth/registration.feature"


# ── Scenarios ───────────────────────────────────────────────────────────────


@scenario(FEATURE, "Registration returns an access and refresh token pair")
def test_registration_returns_tokens() -> None:
    pass


@scenario(FEATURE, "Each registration creates a unique player identity")
def test_unique_player_ids() -> None:
    pass


@scenario(FEATURE, "Registration response contains no password or credential data")
def test_no_credential_data() -> None:
    pass


# ── When ────────────────────────────────────────────────────────────────────


@when("the visitor calls the anonymous registration endpoint", target_fixture="ctx")
def call_anonymous(ctx: dict, unauth_client: TestClient, pg: AsyncMock) -> dict:
    pg.execute = AsyncMock(side_effect=[_make_result(), _make_result(), _make_result()])
    pg.commit = AsyncMock()
    ctx["response"] = unauth_client.post("/api/v1/auth/anonymous")
    assert pg.execute.await_count == 3
    return ctx


@when("the visitor registers anonymously twice", target_fixture="ctx")
def call_anonymous_twice(ctx: dict, unauth_client: TestClient, pg: AsyncMock) -> dict:
    pg.execute = AsyncMock(side_effect=[_make_result(), _make_result(), _make_result()])
    pg.commit = AsyncMock()
    ctx["resp1"] = unauth_client.post("/api/v1/auth/anonymous")
    assert pg.execute.await_count == 3

    pg.execute = AsyncMock(side_effect=[_make_result(), _make_result(), _make_result()])
    pg.commit = AsyncMock()
    ctx["resp2"] = unauth_client.post("/api/v1/auth/anonymous")
    assert pg.execute.await_count == 3
    return ctx


# ── Then ────────────────────────────────────────────────────────────────────


@then("the response contains an access token and a refresh token")
def check_token_pair(ctx: dict) -> None:
    data = ctx["response"].json()["data"]
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["access_token"]
    assert data["refresh_token"]


@then("the player identity is anonymous")
def check_anonymous(ctx: dict) -> None:
    data = ctx["response"].json()["data"]
    assert data["is_anonymous"] is True
    assert "player_id" in data


@then("the two registrations have different player_ids")
def check_unique_ids(ctx: dict) -> None:
    id1 = ctx["resp1"].json()["data"]["player_id"]
    id2 = ctx["resp2"].json()["data"]["player_id"]
    assert id1 != id2


@then("no password or credential fields are present in the response")
def check_no_credentials(ctx: dict) -> None:
    payload = ctx["response"].json()
    forbidden_terms = ("password", "hash", "secret", "credential")

    def assert_no_forbidden_keys(value: object, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, nested_value in value.items():
                key_lower = str(key).lower()
                for forbidden in forbidden_terms:
                    assert forbidden not in key_lower, (
                        f"Forbidden field found in response: {path}.{key}"
                    )
                assert_no_forbidden_keys(nested_value, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                assert_no_forbidden_keys(item, f"{path}[{index}]")

    assert_no_forbidden_keys(payload)
