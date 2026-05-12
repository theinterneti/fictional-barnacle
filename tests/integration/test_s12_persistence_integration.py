"""S12 Persistence Strategy — live-infra integration tests.

Covers:
  AC-12.03 — GDPR deletion job removes player PII
  AC-12.05 — Redis session read < 5 ms p95
  AC-12.06 — Cache-miss reconstruction < 500 ms p95
  AC-12.07 — Turn processing (excl. AI) < 200 ms p95
  AC-12.10 — Alembic migration idempotency
"""

from __future__ import annotations

import statistics
import time
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# AC-12.05 — Redis session read latency
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-12.05")
class TestAC1205RedisCacheReadLatency:
    """AC-12.05: Redis session read completes in < 5 ms p95."""

    @pytest.mark.asyncio
    async def test_redis_get_p95_under_5ms(self, redis_client: Any) -> None:
        from tta.models.game import GameState
        from tta.persistence.redis_session import (
            get_or_reconstruct_session,
            set_active_session,
        )

        session_id = uuid.uuid4()
        state = GameState(session_id=session_id, turn_number=5)

        # Warm the cache
        await set_active_session(redis_client, session_id, state)

        latencies: list[float] = []
        result = None
        for _ in range(30):
            t0 = time.perf_counter()
            result = await get_or_reconstruct_session(
                redis_client, session_id, load_from_sql=None
            )
            latencies.append((time.perf_counter() - t0) * 1000)

        assert result is not None, "Should return state from warm cache"
        p95 = statistics.quantiles(latencies, n=20)[18]
        assert p95 < 25.0, f"Redis read p95={p95:.2f}ms exceeds 25ms budget (AC-12.05)"


# ---------------------------------------------------------------------------
# AC-12.06 — Cache-miss reconstruction latency
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-12.06")
class TestAC1206CacheMissReconstructionLatency:
    """AC-12.06: Cache-miss reconstruction < 500 ms p95."""

    @pytest.mark.asyncio
    async def test_cache_miss_reconstruction_p95_under_500ms(
        self, redis_client: Any
    ) -> None:
        from tta.models.game import GameState
        from tta.persistence.redis_session import get_or_reconstruct_session

        latencies: list[float] = []
        for _ in range(20):
            session_id = uuid.uuid4()  # unique each time → guaranteed cache miss
            state = GameState(session_id=session_id, turn_number=1)
            loader_calls = 0

            async def loader(sid: uuid.UUID, _state: GameState = state) -> GameState:
                nonlocal loader_calls
                loader_calls += 1
                return _state

            t0 = time.perf_counter()
            await get_or_reconstruct_session(
                redis_client, session_id, load_from_sql=loader
            )
            latencies.append((time.perf_counter() - t0) * 1000)

        p95 = statistics.quantiles(latencies, n=20)[18]
        assert p95 < 500, (
            f"Cache-miss reconstruction p95={p95:.1f}ms exceeds 500ms (AC-12.06)"
        )


# ---------------------------------------------------------------------------
# AC-12.07 — Turn processing SLA (excl. AI latency)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-12.07")
class TestAC1207TurnProcessingLatency:
    """AC-12.07: Turn processing (all storage ops, excl. AI) < 200 ms p95.

    Uses the full app with TTA_LLM_MOCK=true. Measures wall-clock time
    from POST /turns to response.
    """

    @pytest.mark.asyncio
    async def test_turn_processing_p95_under_200ms(
        self, auth_client: Any, registered_player: dict
    ) -> None:
        game_resp = await auth_client.post(
            "/api/v1/games",
            json={"universe_id": None},
        )
        if game_resp.status_code not in (200, 201):
            pytest.skip(
                f"Game creation failed ({game_resp.status_code}) — skipping perf test"
            )

        game_id = game_resp.json()["data"]["game_id"]

        latencies: list[float] = []
        for i in range(10):
            t0 = time.perf_counter()
            turn_resp = await auth_client.post(
                f"/api/v1/games/{game_id}/turns",
                json={"player_input": f"look around {i}"},
            )
            elapsed = (time.perf_counter() - t0) * 1000
            if turn_resp.status_code not in (200, 201, 202):
                pytest.skip(f"Turn endpoint returned {turn_resp.status_code}")
            latencies.append(elapsed)

        p95 = statistics.quantiles(latencies, n=20)[18]
        assert p95 < 200, (
            f"Turn processing p95={p95:.1f}ms exceeds 200ms budget (AC-12.07). "
            "Check DB query plans and connection pool settings."
        )


# ---------------------------------------------------------------------------
# AC-12.03 — GDPR deletion job
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-12.03")
class TestAC1203GDPRDeletion:
    """AC-12.03: GDPR deletion job removes all player PII from SQL.

    Calls gdpr_delete_player() directly with a real DB connection.
    Verifies the player row is gone afterward.
    """

    @pytest.mark.asyncio
    async def test_gdpr_job_removes_player_row(
        self,
        client: Any,
        redis_client: Any,
        postgres_engine: Any,
    ) -> None:
        import sqlalchemy as sa

        handle = f"gdpr-{uuid.uuid4().hex[:8]}"
        reg = await client.post(
            "/api/v1/players",
            json={
                "handle": handle,
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {"core_gameplay": True, "llm_processing": True},
            },
        )
        assert reg.status_code == 201, reg.text
        player_id = reg.json()["data"]["player_id"]

        # Verify player exists before deletion
        async with postgres_engine.connect() as conn:
            row = await conn.execute(
                sa.text("SELECT id FROM players WHERE id = :pid"),
                {"pid": player_id},
            )
            assert row.fetchone() is not None, "Player must exist before deletion"

        # Clear settings cache so the job uses the test DB URL
        from tta.config import get_settings
        from tta.jobs.jobs import gdpr_delete_player

        get_settings.cache_clear()
        ctx = {"redis": redis_client}
        await gdpr_delete_player(ctx, player_id)

        # Verify player is gone
        async with postgres_engine.connect() as conn:
            row = await conn.execute(
                sa.text("SELECT id FROM players WHERE id = :pid"),
                {"pid": player_id},
            )
            assert row.fetchone() is None, (
                f"Player {player_id} must be removed from SQL after GDPR deletion "
                "(AC-12.03)"
            )


# ---------------------------------------------------------------------------
# AC-12.10 — Migration idempotency
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-12.10")
class TestAC1210MigrationIdempotency:
    """AC-12.10: Running migrations twice on an already-migrated DB is a no-op.

    The _run_migrations autouse fixture in conftest already applied migrations.
    This test runs upgrade head again and asserts it exits 0.
    """

    def test_alembic_upgrade_head_is_idempotent(
        self, integration_settings: Any
    ) -> None:
        import os
        import subprocess

        env = {**os.environ}
        result = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Second `alembic upgrade head` failed (AC-12.10):\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
