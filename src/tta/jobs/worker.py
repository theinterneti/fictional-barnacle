"""ARQ WorkerSettings for the TTA job runner (S48 FR-48.01)."""

from __future__ import annotations

from arq.connections import RedisSettings
from arq.cron import cron

from tta.config import get_settings
from tta.jobs.jobs import (
    game_backfill,
    gdpr_delete_player,
    retention_sweep,
    session_cleanup,
)

settings = get_settings()


class WorkerSettings:
    """ARQ worker configuration.

    Start with: ``uv run arq tta.jobs.worker.WorkerSettings``
    """

    functions = [gdpr_delete_player, retention_sweep, session_cleanup, game_backfill]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 1800
    keep_result = 3600
    queue_name = "tta:jobs"
    cron_jobs = [
        cron(retention_sweep, hour=3, minute=0),
        cron(session_cleanup, minute=0),
    ]
