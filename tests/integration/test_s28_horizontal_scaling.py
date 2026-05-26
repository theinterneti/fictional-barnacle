"""S28 AC-28.08 — horizontal scaling readiness.

This is a local practical surrogate for "two application instances behind a load
balancer": two independent FastAPI app objects use the same PostgreSQL and Redis
test services. Instance A accepts/processes the turn; instance B serves the SSE
stream. Passing this test proves turn-result delivery is not process-local when
the Redis backend is selected.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from tta.config import Settings

pytestmark = pytest.mark.integration


@asynccontextmanager
async def _running_app(settings: Settings) -> AsyncIterator[Any]:
    """Start one FastAPI application lifespan and always bound shutdown time."""
    from tta.api.app import create_app

    app = create_app(settings)
    ctx = app.router.lifespan_context(app)
    await ctx.__aenter__()
    try:
        yield app
    finally:
        try:
            await asyncio.wait_for(ctx.__aexit__(None, None, None), timeout=10.0)
        finally:
            from tta.observability.langfuse import shutdown_langfuse

            shutdown_langfuse()


async def _register_player(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/players",
        json={
            "handle": "ac-2808-horizontal-player",
            "age_13_plus_confirmed": True,
            "consent_version": "1.0",
            "consent_categories": {"core_gameplay": True, "llm_processing": True},
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    return {
        "player_id": data["player_id"],
        "session_token": data["session_token"],
    }


async def _create_game(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post("/api/v1/games", json={}, headers=headers)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["game_id"])


async def _submit_turn(
    client: AsyncClient,
    game_id: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/games/{game_id}/turns",
        json={"input": "Look around the room"},
        headers=headers,
    )
    assert resp.status_code == 202, resp.text
    return resp.json()["data"]


@pytest.mark.spec("AC-28.08")
@pytest.mark.asyncio
async def test_turn_submitted_on_instance_a_streams_from_instance_b(
    integration_settings: Settings,
    redis_client: Any,
) -> None:
    """Instance B receives turn events published by instance A via Redis."""
    await redis_client.flushdb()
    settings = integration_settings.model_copy(
        update={"turn_result_backend": "redis"},
    )

    async with _running_app(settings) as app_a, _running_app(settings) as app_b:
        async with (
            AsyncClient(
                transport=ASGITransport(app=app_a),
                base_url="http://instance-a",
            ) as client_a,
            AsyncClient(
                transport=ASGITransport(app=app_b),
                base_url="http://instance-b",
            ) as client_b,
        ):
            player = await _register_player(client_a)
            headers = {"Authorization": f"Bearer {player['session_token']}"}
            game_id = await _create_game(client_a, headers)
            turn_data = await _submit_turn(client_a, game_id, headers)

            event_types: list[str] = []
            event_payloads: dict[str, list[dict[str, Any]]] = {}
            current_event_type: str | None = None
            async with asyncio.timeout(10.0):
                async with client_b.stream(
                    "GET",
                    f"/api/v1/games/{game_id}/stream",
                    headers={**headers, "Accept": "text/event-stream"},
                ) as response:
                    assert response.status_code == 200
                    assert "text/event-stream" in response.headers.get(
                        "content-type",
                        "",
                    )

                    async for line in response.aiter_lines():
                        if line.startswith("event:"):
                            current_event_type = line.split(":", 1)[1].strip()
                            event_types.append(current_event_type)
                        elif line.startswith("data:") and current_event_type:
                            event_payloads.setdefault(current_event_type, []).append(
                                json.loads(line.split(":", 1)[1].strip()),
                            )
                            if current_event_type == "narrative_end":
                                break

            turn_id = turn_data["turn_id"]
            assert turn_id
            assert "narrative" in event_types
            assert "narrative_end" in event_types
            assert any(
                payload.get("turn_id") == turn_id
                for payload in event_payloads.get("narrative", [])
            )
            assert any(
                payload.get("turn_id") == turn_id
                for payload in event_payloads.get("narrative_end", [])
            )
