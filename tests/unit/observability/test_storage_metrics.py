"""Tests for storage-layer Prometheus metrics (AC-12.05, AC-12.07)."""

from __future__ import annotations

from tta.observability.metrics import (
    CACHE_RECONSTRUCTION_DURATION,
    CACHE_RECONSTRUCTION_TOTAL,
    REDIS_CACHE_READ_DURATION,
    REDIS_CACHE_WRITE_DURATION,
    REDIS_KEYS_WITHOUT_TTL,
    REGISTRY,
    TURN_STORAGE_OPS_DURATION,
)


class TestRedisMetricsDefined:
    """All storage metrics exist in the custom registry."""

    def test_read_histogram_exists(self) -> None:
        assert REDIS_CACHE_READ_DURATION is not None
        assert REDIS_CACHE_READ_DURATION._name == (
            "tta_redis_cache_read_duration_seconds"
        )

    def test_write_histogram_exists(self) -> None:
        assert REDIS_CACHE_WRITE_DURATION is not None
        assert REDIS_CACHE_WRITE_DURATION._name == (
            "tta_redis_cache_write_duration_seconds"
        )

    def test_storage_ops_histogram_exists(self) -> None:
        assert TURN_STORAGE_OPS_DURATION is not None
        assert TURN_STORAGE_OPS_DURATION._name == (
            "tta_turn_storage_ops_duration_seconds"
        )

    def test_reconstruction_counter_exists(self) -> None:
        assert CACHE_RECONSTRUCTION_TOTAL is not None
        assert CACHE_RECONSTRUCTION_TOTAL._name == "tta_cache_reconstruction"

    def test_reconstruction_duration_exists(self) -> None:
        assert CACHE_RECONSTRUCTION_DURATION is not None
        assert CACHE_RECONSTRUCTION_DURATION._name == (
            "tta_cache_reconstruction_duration_seconds"
        )

    def test_keys_without_ttl_gauge_exists(self) -> None:
        assert REDIS_KEYS_WITHOUT_TTL is not None
        assert REDIS_KEYS_WITHOUT_TTL._name == ("tta_redis_keys_without_ttl")


class TestMetricsRegistered:
    """All new metrics are on the custom REGISTRY."""

    def test_all_registered(self) -> None:
        names = {m.name for m in REGISTRY.collect()}
        expected = {
            "tta_redis_cache_read_duration_seconds",
            "tta_redis_cache_write_duration_seconds",
            "tta_turn_storage_ops_duration_seconds",
            "tta_cache_reconstruction",
            "tta_cache_reconstruction_duration_seconds",
            "tta_redis_keys_without_ttl",
        }
        assert expected.issubset(names)
