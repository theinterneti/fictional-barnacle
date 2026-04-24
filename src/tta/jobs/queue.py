"""ArqQueue abstraction over ARQ Redis queue (S48 FR-48.02)."""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from tta.jobs.models import JobStatus

log = structlog.get_logger(__name__)

# ARQ status strings to TTA JobStatus mapping
_ARQ_STATUS_MAP = {
    "queued": JobStatus.QUEUED,
    "in_progress": JobStatus.RUNNING,
    "complete": JobStatus.COMPLETE,
    "not_found": JobStatus.NOT_FOUND,
    "deferred": JobStatus.DEFERRED,
}


class ArqQueue:
    """Thin abstraction over ARQ's ArqRedis for job enqueueing."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._pool: Any = None

    async def _get_pool(self) -> Any:
        if self._pool is None:
            from arq import create_pool
            from arq.connections import RedisSettings

            self._pool = await create_pool(
                RedisSettings.from_dsn(self._redis_url),
                job_serializer=None,
                job_deserializer=None,
            )
        return self._pool

    async def enqueue(
        self,
        job_fn: str,
        *args: object,
        _job_id: str | None = None,
        **kwargs: object,
    ) -> str:
        """Enqueue a job by function name. Returns the job_id."""
        pool = await self._get_pool()
        job_id = _job_id or str(uuid.uuid4())
        await pool.enqueue_job(job_fn, *args, _job_id=job_id, **kwargs)
        log.info("job_enqueued", job_fn=job_fn, job_id=job_id)
        return job_id

    async def job_status(self, job_id: str) -> JobStatus | None:
        """Return current status of a job, or None if not found."""
        try:
            from arq.jobs import Job
            from arq.jobs import JobStatus as ArqJobStatus

            pool = await self._get_pool()
            job = Job(job_id, pool)
            status = await job.status()
            if status == ArqJobStatus.not_found:
                return JobStatus.NOT_FOUND
            arq_str = status.value if hasattr(status, "value") else str(status)
            return _ARQ_STATUS_MAP.get(arq_str, JobStatus.NOT_FOUND)
        except Exception as exc:
            log.warning("job_status_error", job_id=job_id, error=str(exc))
            return None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
