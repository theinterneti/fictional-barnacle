"""Job status enum (S48)."""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    NOT_FOUND = "not_found"
    DEFERRED = "deferred"
