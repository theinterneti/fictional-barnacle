"""Data retention policy constants per S17 §4 FR-17.14.

Provides machine-readable retention periods and a lookup
function for documentation and programmatic enforcement.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """A single retention rule."""

    category: str
    retention_days: int | None  # None = until account deletion
    justification: str


# S17 §4 FR-17.14 — authoritative retention periods
_POLICIES: list[RetentionPolicy] = [
    RetentionPolicy(
        "active_session_redis",
        1,
        "Sessions are ephemeral; inactive sessions expire after 24h TTL",
    ),
    RetentionPolicy(
        "completed_session_postgresql",
        90,
        "Allows players to review recent games",
    ),
    RetentionPolicy(
        "player_profile",
        None,
        "Players control their account lifetime",
    ),
    RetentionPolicy(
        "llm_interaction_langfuse",
        90,
        "Needed for quality improvement and debugging",
    ),
    RetentionPolicy(
        "application_logs",
        30,
        "Operational troubleshooting",
    ),
    RetentionPolicy(
        "metrics_prometheus",
        30,
        "Trend analysis",
    ),
    RetentionPolicy(
        "traces_jaeger",
        7,
        "Short-term debugging",
    ),
    RetentionPolicy(
        "soft_deleted_game_postgresql",
        3,
        "FR-27.17: soft-deleted data purged after 72 hours",
    ),
]


def get_retention_policy(category: str) -> RetentionPolicy | None:
    """Look up a retention policy by category name."""
    for policy in _POLICIES:
        if policy.category == category:
            return policy
    return None


def get_all_policies() -> list[RetentionPolicy]:
    """Return every retention policy."""
    return list(_POLICIES)
