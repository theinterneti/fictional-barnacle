from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def workflow_module():
    path = Path("scripts/workflow_state.py")
    spec = importlib.util.spec_from_file_location("workflow_state", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_allowed_transition_is_linear_and_explicit(workflow_module) -> None:
    item = workflow_module.WorkItem(
        id="FB-0001",
        title="Add thing",
        stage="PLAN_APPROVED",
        spec_ref="specs/65-local-ci-gate.md",
        plan_ref="plans/ops.md",
    )

    assert workflow_module.can_advance(item, "IMPLEMENTING").allowed is True
    assert workflow_module.can_advance(item, "MERGED").allowed is False


def test_implementation_requires_existing_approved_spec_and_plan(
    workflow_module,
) -> None:
    item = workflow_module.WorkItem(
        id="FB-0002",
        title="Missing plan",
        stage="PLAN_APPROVED",
        spec_ref="specs/65-local-ci-gate.md",
        plan_ref="plans/missing.md",
    )

    decision = workflow_module.can_advance(item, "IMPLEMENTING")

    assert decision.allowed is False
    assert "plan_ref does not exist" in decision.reason


def test_local_gate_green_requires_passing_gate_evidence(workflow_module) -> None:
    item = workflow_module.WorkItem(
        id="FB-0003",
        title="No gate evidence",
        stage="TESTING",
        spec_ref="specs/65-local-ci-gate.md",
        plan_ref="plans/ops.md",
        last_gate_result="fail",
    )

    decision = workflow_module.can_advance(item, "LOCAL_GATE_GREEN")

    assert decision.allowed is False
    assert "last_gate_result=pass" in decision.reason


def test_next_action_prefers_first_nonterminal_item(workflow_module) -> None:
    items = [
        workflow_module.WorkItem(id="FB-DONE", title="Done", stage="RELEASED"),
        workflow_module.WorkItem(id="FB-NEXT", title="Next", stage="APPROVED_SPEC"),
    ]

    assert workflow_module.next_item(items).id == "FB-NEXT"


def test_status_report_groups_items_by_stage(workflow_module) -> None:
    items = [
        workflow_module.WorkItem(id="FB-A", title="A", stage="APPROVED_SPEC"),
        workflow_module.WorkItem(id="FB-B", title="B", stage="APPROVED_SPEC"),
        workflow_module.WorkItem(id="FB-C", title="C", stage="IMPLEMENTING"),
    ]

    report = workflow_module.render_status(items)

    assert "APPROVED_SPEC: 2" in report
    assert "IMPLEMENTING: 1" in report
