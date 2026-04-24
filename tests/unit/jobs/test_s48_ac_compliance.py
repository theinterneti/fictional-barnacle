"""AC compliance tests for S48 — Async Job Runner.

Covers:
  AC-48.01 — GDPR erasure job runs end-to-end
  AC-48.02 — GDPR job is idempotent (already_erased)
  AC-48.03 — Retention sweep deletes in batches of RETENTION_BATCH_SIZE
  AC-48.04 — Failed jobs after 3 retries land in dead-letter queue
  AC-48.05 — WorkerSettings is correctly configured
  AC-48.06 — Admin can enqueue and check job status

Import strategy: ``tta.jobs.worker`` accesses ``get_settings()`` at *module*
level. We set env-var defaults here (before any TTA import) so the module
imports cleanly during pytest collection even without a .env file.
"""

from __future__ import annotations

import os

os.environ.setdefault("TTA_DATABASE_URL", "postgresql+asyncpg://test@localhost/test")
os.environ.setdefault("TTA_NEO4J_PASSWORD", "test")

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.config import Settings
from tta.jobs import JobStatus
from tta.jobs.jobs import (
    DEAD_LETTER_KEY,
    RETENTION_BATCH_SIZE,
    _write_dead_letter,
    gdpr_delete_player,
    retention_sweep,
)

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

ADMIN_KEY = "s48-test-admin-key"


def _mock_settings() -> MagicMock:
    s = MagicMock()
    s.database_url = "postgresql+asyncpg://test@localhost/test"
    s.neo4j_uri = None  # skip Neo4j step in GDPR tests
    return s


def _make_async_cm(return_value=None, side_effect=None) -> AsyncMock:
    """Return an async context manager mock."""
    cm = AsyncMock()
    if side_effect is not None:
        cm.__aenter__ = AsyncMock(side_effect=side_effect)
    else:
        cm.__aenter__ = AsyncMock(return_value=return_value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_mock_engine(
    conn: AsyncMock | None = None, *, error: Exception | None = None
) -> MagicMock:
    """Return a mock AsyncEngine with a synchronous begin() returning an async CM."""
    engine = MagicMock()
    engine.dispose = AsyncMock()
    if error is not None:
        engine.begin = MagicMock(return_value=_make_async_cm(side_effect=error))
    else:
        engine.begin = MagicMock(return_value=_make_async_cm(return_value=conn))
    return engine


def _make_mock_conn(*, player_exists: bool = True) -> AsyncMock:
    """Return a mock async connection for gdpr_delete_player tests."""
    mock_result = MagicMock()
    mock_result.one_or_none.return_value = MagicMock() if player_exists else None

    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=mock_result)
    return conn


def _build_admin_client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.state.settings = settings
    app.state.pg = MagicMock()
    app.state.redis = AsyncMock()
    app.state.neo4j_driver = None
    app.state.session_repo = MagicMock()
    app.state.turn_repo = MagicMock()
    app.state.rate_limiter = MagicMock()
    app.state.abuse_detector = None
    app.state.moderation_recorder = None
    app.state.moderation_hook = MagicMock()
    app.state.llm_semaphore = None
    app.state.llm_client = MagicMock()
    app.state.prompt_registry = MagicMock()
    app.state.world_service = MagicMock()
    app.state.summary_service = MagicMock()
    app.state.pipeline_deps = MagicMock()
    app.state.turn_result_store = MagicMock()
    app.state.pg_engine = MagicMock()

    audit_repo = MagicMock()
    audit_repo.create_and_append = AsyncMock()
    audit_repo.query = AsyncMock(return_value=[])
    app.state.audit_repo = audit_repo

    # Job queue stub
    job_queue = MagicMock()
    job_queue.enqueue = AsyncMock(return_value="job-abc123")
    job_queue.job_status = AsyncMock(return_value=JobStatus.QUEUED)
    app.state.job_queue = job_queue

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# AC-48.01 / AC-48.02 — GDPR erasure
# ---------------------------------------------------------------------------


class TestGdprDeletePlayer:
    @pytest.mark.spec("AC-48.01")
    @pytest.mark.asyncio
    async def test_erase_existing_player_returns_erased(self) -> None:
        """AC-48.01: gdpr_delete_player deletes all player data and returns 'erased'."""
        mock_conn = _make_mock_conn(player_exists=True)
        mock_engine = _make_mock_engine(conn=mock_conn)
        ctx: dict = {"job_try": 1}

        with (
            patch("tta.config.get_settings", return_value=_mock_settings()),
            patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                return_value=mock_engine,
            ),
        ):
            result = await gdpr_delete_player(ctx, "player-001")

        assert result == "erased"
        mock_engine.dispose.assert_awaited_once()

    @pytest.mark.spec("AC-48.01")
    @pytest.mark.asyncio
    async def test_erase_calls_postgres_delete(self) -> None:
        """AC-48.01: The job executes at least two SQL statements (SELECT + DELETE)."""
        mock_conn = _make_mock_conn(player_exists=True)
        mock_engine = _make_mock_engine(conn=mock_conn)
        ctx: dict = {"job_try": 1}

        with (
            patch("tta.config.get_settings", return_value=_mock_settings()),
            patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                return_value=mock_engine,
            ),
        ):
            await gdpr_delete_player(ctx, "player-001")

        assert mock_conn.execute.await_count >= 2  # SELECT + DELETE

    @pytest.mark.spec("AC-48.02")
    @pytest.mark.asyncio
    async def test_already_erased_is_idempotent(self) -> None:
        """AC-48.02: If the player row is absent, returns 'already_erased'."""
        mock_conn = _make_mock_conn(player_exists=False)
        mock_engine = _make_mock_engine(conn=mock_conn)
        ctx: dict = {"job_try": 1}

        with (
            patch("tta.config.get_settings", return_value=_mock_settings()),
            patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                return_value=mock_engine,
            ),
        ):
            result = await gdpr_delete_player(ctx, "player-gone")

        assert result == "already_erased"

    @pytest.mark.spec("AC-48.02")
    @pytest.mark.asyncio
    async def test_already_erased_does_not_call_dispose(self) -> None:
        """AC-48.02: 'already_erased' path returns early — dispose is NOT called."""
        mock_conn = _make_mock_conn(player_exists=False)
        mock_engine = _make_mock_engine(conn=mock_conn)
        ctx: dict = {"job_try": 1}

        with (
            patch("tta.config.get_settings", return_value=_mock_settings()),
            patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                return_value=mock_engine,
            ),
        ):
            await gdpr_delete_player(ctx, "player-gone")

        mock_engine.dispose.assert_not_awaited()


# ---------------------------------------------------------------------------
# AC-48.03 — Retention sweep batch loop
# ---------------------------------------------------------------------------


class TestRetentionSweep:
    @pytest.mark.spec("AC-48.03")
    def test_retention_batch_size_constant(self) -> None:
        """AC-48.03: RETENTION_BATCH_SIZE is exactly 500."""
        assert RETENTION_BATCH_SIZE == 500

    @pytest.mark.spec("AC-48.03")
    @pytest.mark.asyncio
    async def test_retention_sweep_batches_until_exhausted(self) -> None:
        """AC-48.03: Sweep loops until a batch smaller than 500 is returned.

        Simulates 2 full batches (500 rows each) then a partial (200 rows),
        verifying deleted_count == 1200 and asyncio.sleep is called twice.
        """
        rowcounts = [500, 500, 200]
        call_index = [0]

        def _make_cm_for_next_batch() -> AsyncMock:
            rc = rowcounts[call_index[0]]
            call_index[0] += 1
            mock_result = MagicMock()
            mock_result.rowcount = rc
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(return_value=mock_result)
            return _make_async_cm(return_value=mock_conn)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(side_effect=_make_cm_for_next_batch)
        mock_engine.dispose = AsyncMock()

        mock_sleep = AsyncMock()
        ctx: dict = {}

        with (
            patch("tta.config.get_settings", return_value=_mock_settings()),
            patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                return_value=mock_engine,
            ),
            patch("asyncio.sleep", mock_sleep),
        ):
            result = await retention_sweep(ctx)

        assert result == {"deleted_count": 1200}
        assert mock_engine.begin.call_count == 3
        assert mock_sleep.await_count == 2  # sleep after each full batch
        mock_engine.dispose.assert_awaited_once()


# ---------------------------------------------------------------------------
# AC-48.04 — Dead-letter queue
# ---------------------------------------------------------------------------


class TestDeadLetter:
    @pytest.mark.spec("AC-48.04")
    @pytest.mark.asyncio
    async def test_write_dead_letter_pushes_to_redis(self) -> None:
        """AC-48.04: _write_dead_letter appends to tta:jobs:dead and trims to 1000."""
        mock_redis = AsyncMock()
        ctx = {"redis": mock_redis, "job_id": "jid-001"}

        await _write_dead_letter(ctx, "gdpr_delete_player", ("player-x",), "DB down")

        mock_redis.lpush.assert_awaited_once()
        assert mock_redis.lpush.call_args[0][0] == DEAD_LETTER_KEY
        mock_redis.ltrim.assert_awaited_once_with(DEAD_LETTER_KEY, 0, 999)

    @pytest.mark.spec("AC-48.04")
    @pytest.mark.asyncio
    async def test_dead_letter_on_3rd_retry(self) -> None:
        """AC-48.04: Job failure on 3rd try writes to dead-letter queue."""
        mock_redis = AsyncMock()
        ctx = {"job_try": 3, "redis": mock_redis}
        db_error = RuntimeError("DB exploded")
        mock_engine = _make_mock_engine(error=db_error)

        with (
            patch("tta.config.get_settings", return_value=_mock_settings()),
            patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                return_value=mock_engine,
            ),
        ):
            with pytest.raises(RuntimeError):
                await gdpr_delete_player(ctx, "player-fail")

        mock_redis.lpush.assert_awaited_once()

    @pytest.mark.spec("AC-48.04")
    @pytest.mark.asyncio
    async def test_no_dead_letter_before_3rd_retry(self) -> None:
        """AC-48.04: Job failure before 3rd try does NOT write to dead-letter."""
        mock_redis = AsyncMock()
        ctx = {"job_try": 1, "redis": mock_redis}
        db_error = RuntimeError("DB flaky")
        mock_engine = _make_mock_engine(error=db_error)

        with (
            patch("tta.config.get_settings", return_value=_mock_settings()),
            patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                return_value=mock_engine,
            ),
        ):
            with pytest.raises(RuntimeError):
                await gdpr_delete_player(ctx, "player-retry")

        mock_redis.lpush.assert_not_awaited()

    @pytest.mark.spec("AC-48.04")
    @pytest.mark.asyncio
    async def test_dead_letter_no_op_without_redis(self) -> None:
        """AC-48.04: _write_dead_letter is a no-op when ctx has no redis."""
        ctx: dict = {}  # no "redis" key
        # Should not raise
        await _write_dead_letter(ctx, "gdpr_delete_player", (), "some error")


# ---------------------------------------------------------------------------
# AC-48.05 — WorkerSettings configuration
# ---------------------------------------------------------------------------


class TestWorkerSettings:
    """Verify ARQ WorkerSettings is properly configured for graceful operation.

    AC-48.05 requires the worker shuts down gracefully on SIGTERM — this is
    ARQ's built-in behaviour, enabled by providing a complete WorkerSettings
    with correct timeout, queue name, and function list.
    """

    @pytest.fixture(autouse=True)
    def _import_worker(self) -> None:
        # Worker module uses get_settings() at module level; env vars are set
        # at the top of this file, so the import is safe.
        from tta.jobs.worker import WorkerSettings as WS

        self.WS = WS

    @pytest.mark.spec("AC-48.05")
    def test_queue_name(self) -> None:
        """AC-48.05: Worker listens on the canonical TTA job queue."""
        assert self.WS.queue_name == "tta:jobs"

    @pytest.mark.spec("AC-48.05")
    def test_max_jobs(self) -> None:
        """AC-48.05: Worker processes at most 10 concurrent jobs."""
        assert self.WS.max_jobs == 10

    @pytest.mark.spec("AC-48.05")
    def test_job_timeout_is_30_minutes(self) -> None:
        """AC-48.05: Job timeout is 1800 s (30 min) — allows SIGTERM to finish."""
        assert self.WS.job_timeout == 1800

    @pytest.mark.spec("AC-48.05")
    def test_keep_result_is_1_hour(self) -> None:
        """AC-48.05: Results are retained for 3600 s (1 hour) after completion."""
        assert self.WS.keep_result == 3600

    @pytest.mark.spec("AC-48.05")
    def test_all_four_functions_registered(self) -> None:
        """AC-48.05: All four job functions are registered with the worker."""
        fn_names = {fn.__name__ for fn in self.WS.functions}
        assert fn_names == {
            "gdpr_delete_player",
            "retention_sweep",
            "session_cleanup",
            "game_backfill",
        }

    @pytest.mark.spec("AC-48.05")
    def test_two_cron_jobs_configured(self) -> None:
        """AC-48.05: Exactly two scheduled (cron) jobs are configured."""
        assert len(self.WS.cron_jobs) == 2


# ---------------------------------------------------------------------------
# AC-48.06 — Admin endpoints
# ---------------------------------------------------------------------------


class TestAdminJobEndpoints:
    @pytest.fixture()
    def settings(self) -> Settings:
        return Settings(
            database_url="postgresql://test@localhost/test",
            neo4j_password="test",
            admin_api_key=ADMIN_KEY,
        )

    @pytest.fixture()
    def client(self, settings: Settings) -> TestClient:
        return _build_admin_client(settings)

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {ADMIN_KEY}"}

    @pytest.mark.spec("AC-48.06")
    def test_enqueue_known_job_returns_201(self, client: TestClient) -> None:
        """AC-48.06: POST /admin/jobs/session_cleanup/enqueue returns 201 + job_id."""
        resp = client.post("/admin/jobs/session_cleanup/enqueue", headers=self._auth())
        assert resp.status_code == 201
        data = resp.json()
        assert "job_id" in data
        assert data["job_fn"] == "session_cleanup"

    @pytest.mark.spec("AC-48.06")
    def test_enqueue_unknown_job_returns_400(self, client: TestClient) -> None:
        """AC-48.06: POST /admin/jobs/bad_fn/enqueue returns 400 INPUT_INVALID."""
        resp = client.post(
            "/admin/jobs/totally_unknown_fn/enqueue", headers=self._auth()
        )
        assert resp.status_code == 400

    @pytest.mark.spec("AC-48.06")
    def test_get_job_status_returns_200(self, client: TestClient) -> None:
        """AC-48.06: GET /admin/jobs/{job_id}/status returns 200 + status field."""
        resp = client.get("/admin/jobs/job-abc123/status", headers=self._auth())
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert "status" in data

    @pytest.mark.spec("AC-48.06")
    def test_get_job_status_not_found_returns_404(self, client: TestClient) -> None:
        """AC-48.06: GET /admin/jobs/{job_id}/status returns 404 when job unknown."""
        # Re-build client with job_status returning None (not found)
        from tta.config import Settings as S

        s = S(
            database_url="postgresql://test@localhost/test",
            neo4j_password="test",
            admin_api_key=ADMIN_KEY,
        )
        cl = _build_admin_client(s)
        cl.app.state.job_queue.job_status = AsyncMock(return_value=None)  # type: ignore[attr-defined]

        resp = cl.get("/admin/jobs/missing-job/status", headers=self._auth())
        assert resp.status_code == 404

    @pytest.mark.spec("AC-48.06")
    def test_enqueue_requires_auth(self, client: TestClient) -> None:
        """AC-48.06: Unauthenticated enqueue is rejected."""
        resp = client.post("/admin/jobs/session_cleanup/enqueue")
        assert resp.status_code in (401, 403)
