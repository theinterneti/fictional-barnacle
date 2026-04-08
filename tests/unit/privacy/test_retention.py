"""Tests for retention policies (S17 §3 FR-17.7 – FR-17.8)."""

from tta.privacy.retention import (
    RetentionPolicy,
    get_all_policies,
    get_retention_policy,
)


class TestRetentionPolicy:
    def test_known_policy_exists(self) -> None:
        policy = get_retention_policy("completed_session_postgresql")
        assert policy is not None
        assert isinstance(policy, RetentionPolicy)

    def test_sessions_90_days(self) -> None:
        policy = get_retention_policy("completed_session_postgresql")
        assert policy is not None
        assert policy.retention_days == 90

    def test_logs_30_days(self) -> None:
        policy = get_retention_policy("application_logs")
        assert policy is not None
        assert policy.retention_days == 30

    def test_traces_7_days(self) -> None:
        policy = get_retention_policy("traces_jaeger")
        assert policy is not None
        assert policy.retention_days == 7

    def test_redis_1_day(self) -> None:
        policy = get_retention_policy("active_session_redis")
        assert policy is not None
        assert policy.retention_days == 1

    def test_unknown_policy_returns_none(self) -> None:
        policy = get_retention_policy("nonexistent_xyz")
        assert policy is None


class TestGetAllPolicies:
    def test_returns_multiple(self) -> None:
        policies = get_all_policies()
        assert len(policies) >= 5

    def test_all_are_frozen(self) -> None:
        for policy in get_all_policies():
            assert isinstance(policy, RetentionPolicy)
            # Frozen dataclass — assignment should raise
            try:
                policy.retention_days = 999  # type: ignore[misc]
                raise AssertionError("Should have raised FrozenInstanceError")
            except AttributeError:
                pass
