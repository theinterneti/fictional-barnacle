"""Integration tests — full turn cycle with real services.

Exercises: POST /turns → pipeline → SSE with Postgres + Redis,
LLM mock mode, and in-memory world service.

Issue #55 acceptance criteria:
  - ≥5 integration tests covering the full vertical slice
  - Tests skip gracefully when docker-compose.test.yml services are down
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import asyncpg
import pytest

if TYPE_CHECKING:
    import httpx

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_sse_events(raw: str) -> list[dict]:
    """Parse raw SSE text into a list of {event, data} dicts."""
    events: list[dict] = []
    current: dict = {}
    for line in raw.split("\n"):
        if line.startswith("event:"):
            current["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            current["data"] = line.split(":", 1)[1].strip()
        elif line.startswith("id:"):
            current["id"] = line.split(":", 1)[1].strip()
        elif line == "" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


async def _create_game(
    client: httpx.AsyncClient,
    headers: dict[str, str],
) -> str:
    """Helper: create a game and return game_id."""
    resp = await client.post(
        "/api/v1/games",
        json={},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["game_id"]


async def _submit_turn(
    client: httpx.AsyncClient,
    game_id: str,
    headers: dict[str, str],
    text: str = "Look around the room",
) -> dict:
    """Helper: submit a turn and return the 202 response data."""
    resp = await client.post(
        f"/api/v1/games/{game_id}/turns",
        json={"input": text},
        headers=headers,
    )
    assert resp.status_code == 202, resp.text
    return resp.json()["data"]


async def _wait_for_turn_complete(
    pg_dsn: str,
    turn_id: str,
    *,
    timeout: float = 5.0,
    interval: float = 0.25,
    extra_columns: str = "",
) -> asyncpg.Record | None:
    """Poll Postgres until turn reaches 'complete' status."""
    cols = "status" + (f", {extra_columns}" if extra_columns else "")
    iterations = int(timeout / interval)
    row: asyncpg.Record | None = None
    for _ in range(iterations):
        await asyncio.sleep(interval)
        conn = await asyncpg.connect(pg_dsn)
        try:
            row = await conn.fetchrow(
                f"SELECT {cols} FROM turns WHERE id = $1",  # noqa: S608
                turn_id,
            )
        finally:
            await conn.close()
        if row and row["status"] == "complete":
            return row
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlayerRegistration:
    """Player registration and authentication flow."""

    async def test_register_player(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """POST /players returns 201 with player_id and session_token."""
        resp = await client.post(
            "/api/v1/players",
            json={
                "handle": "integration-hero",
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {"core_gameplay": True, "llm_processing": True},
            },
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert "player_id" in data
        assert "session_token" in data
        assert data["handle"] == "integration-hero"
        assert "tta_session" in resp.cookies

    async def test_duplicate_handle_rejected(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Registering the same handle twice returns 409."""
        await client.post(
            "/api/v1/players",
            json={
                "handle": "unique-hero",
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {"core_gameplay": True, "llm_processing": True},
            },
        )
        resp = await client.post(
            "/api/v1/players",
            json={
                "handle": "unique-hero",
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {"core_gameplay": True, "llm_processing": True},
            },
        )
        assert resp.status_code == 409


class TestGameCreation:
    """Game session CRUD."""

    async def test_create_game(
        self,
        auth_client: httpx.AsyncClient,
    ) -> None:
        """POST /games returns 201 with game_id and status=active (S27 public state)."""
        resp = await auth_client.post(
            "/api/v1/games",
            json={},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert "game_id" in data
        assert data["status"] == "active"
        assert data["turn_count"] == 0

    async def test_unauthenticated_create_rejected(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """POST /games without auth returns 401."""
        resp = await client.post(
            "/api/v1/games",
            json={},
        )
        assert resp.status_code == 401


class TestTurnSubmission:
    """Turn submission and pipeline execution."""

    async def test_submit_turn_returns_202(
        self,
        auth_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """POST /games/{id}/turns returns 202 with turn_id and stream_url."""
        game_id = await _create_game(auth_client, auth_headers)
        resp = await auth_client.post(
            f"/api/v1/games/{game_id}/turns",
            json={"input": "Look around"},
        )
        assert resp.status_code == 202
        data = resp.json()["data"]
        assert "turn_id" in data
        assert data["turn_number"] == 1
        assert "stream" in data["stream_url"]

    async def test_submit_turn_transitions_game_to_active(
        self,
        auth_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        pg_dsn: str,
    ) -> None:
        """First turn transitions game from 'created' to 'active'."""
        game_id = await _create_game(auth_client, auth_headers)
        turn_data = await _submit_turn(auth_client, game_id, auth_headers)

        row = await _wait_for_turn_complete(pg_dsn, turn_data["turn_id"])
        assert row is not None, "Turn did not reach 'complete' status"

        resp = await auth_client.get(
            f"/api/v1/games/{game_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "active"


class TestSSEStreaming:
    """Server-Sent Events streaming of turn results."""

    async def test_sse_full_cycle(
        self,
        auth_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        pg_dsn: str,
    ) -> None:
        """SSE stream delivers turn_start → narrative_block → turn_complete."""
        game_id = await _create_game(auth_client, auth_headers)
        turn_data = await _submit_turn(auth_client, game_id, auth_headers)

        row = await _wait_for_turn_complete(pg_dsn, turn_data["turn_id"])
        assert row is not None, "Turn did not complete"

        # Read SSE stream
        resp = await auth_client.get(
            f"/api/v1/games/{game_id}/stream",
            headers={
                **auth_headers,
                "Accept": "text/event-stream",
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events = _parse_sse_events(resp.text)
        event_types = [e.get("event") for e in events]

        assert "turn_start" in event_types
        assert "narrative_block" in event_types
        assert "turn_complete" in event_types

        # Verify narrative_block has content
        narrative_events = [e for e in events if e.get("event") == "narrative_block"]
        assert len(narrative_events) >= 1

    async def test_sse_no_turn_returns_error(
        self,
        auth_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """SSE stream returns error event when no turns exist."""
        game_id = await _create_game(auth_client, auth_headers)

        resp = await auth_client.get(
            f"/api/v1/games/{game_id}/stream",
            headers=auth_headers,
        )
        assert resp.status_code == 200

        events = _parse_sse_events(resp.text)
        event_types = [e.get("event") for e in events]
        assert "error" in event_types


class TestTurnPersistence:
    """Verify turn data is persisted to Postgres."""

    async def test_turn_persisted_after_pipeline(
        self,
        auth_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        pg_dsn: str,
    ) -> None:
        """Completed turn has narrative_output and status='complete' in DB."""
        game_id = await _create_game(auth_client, auth_headers)
        turn_data = await _submit_turn(auth_client, game_id, auth_headers)

        row = await _wait_for_turn_complete(
            pg_dsn,
            turn_data["turn_id"],
            extra_columns="narrative_output",
        )
        if row is None or row["status"] != "complete":
            pytest.fail("Turn did not reach 'complete' status within timeout")

        assert row["status"] == "complete"
        assert row["narrative_output"] is not None
        assert len(row["narrative_output"]) > 0


class TestErrorHandling:
    """Edge cases and error paths."""

    async def test_unauthenticated_turn_rejected(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """POST /turns without auth returns 401."""
        # Use a fake game_id since we can't create one without auth
        import uuid

        resp = await client.post(
            f"/api/v1/games/{uuid.uuid4()}/turns",
            json={"input": "hello"},
        )
        assert resp.status_code == 401

    async def test_nonexistent_game_returns_404(
        self,
        auth_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Submitting to a non-existent game returns 404."""
        import uuid

        resp = await auth_client.post(
            f"/api/v1/games/{uuid.uuid4()}/turns",
            json={"input": "hello"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_empty_input_returns_400(
        self,
        auth_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Blank input returns 400 EMPTY_TURN_INPUT (AC-23.11 supersedes AC-1.2)."""
        game_id = await _create_game(auth_client, auth_headers)
        resp = await auth_client.post(
            f"/api/v1/games/{game_id}/turns",
            json={"input": "   "},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        error = resp.json()["error"]
        assert error["code"] == "EMPTY_TURN_INPUT"
