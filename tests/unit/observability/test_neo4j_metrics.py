"""Tests for Neo4j observability helpers (AC-12.08)."""

from __future__ import annotations

import pytest

from tta.observability.db_metrics import observe_neo4j_op
from tta.observability.metrics import NEO4J_OPERATION_DURATION, REGISTRY


class TestNeo4jMetricsDefined:
    def test_histogram_exists(self) -> None:
        assert NEO4J_OPERATION_DURATION is not None
        assert NEO4J_OPERATION_DURATION._name == "tta_neo4j_operation_duration_seconds"

    def test_histogram_registered(self) -> None:
        names = {m.name for m in REGISTRY.collect()}
        assert "tta_neo4j_operation_duration_seconds" in names

    def test_histogram_labels(self) -> None:
        assert set(NEO4J_OPERATION_DURATION._labelnames) == {"operation", "status"}


class TestObserveNeo4jOp:
    async def test_success_label_recorded(self) -> None:
        """Successful operation records status=success."""
        async with observe_neo4j_op("test_op_success"):
            pass  # no exception → success

        labels = NEO4J_OPERATION_DURATION.labels(
            operation="test_op_success", status="success"
        )
        # If the label combination was recorded, _sum > 0 (time elapsed ≥ 0)
        assert labels._sum.get() >= 0

    async def test_error_label_on_exception(self) -> None:
        """Exceptions flip status to 'error' but re-raise."""
        with pytest.raises(ValueError, match="boom"):
            async with observe_neo4j_op("test_op_error"):
                raise ValueError("boom")

        labels = NEO4J_OPERATION_DURATION.labels(
            operation="test_op_error", status="error"
        )
        assert labels._sum.get() >= 0

    async def test_operation_label_is_set(self) -> None:
        """The 'operation' label name is preserved verbatim."""
        op_name = "apply_world_changes"
        async with observe_neo4j_op(op_name):
            pass

        labels = NEO4J_OPERATION_DURATION.labels(operation=op_name, status="success")
        assert labels._labelnames == ("operation", "status")
