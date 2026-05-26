from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def queue_gate_module():
    path = Path("scripts/queue_readiness_gate.py")
    spec = importlib.util.spec_from_file_location("queue_readiness_gate", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_draft_spec_routes_to_spec_polish(queue_gate_module):
    item = {
        "id": "FB-DRAFT",
        "title": "Draft item",
        "spec_ref": "specs/60-crisis-safety-protocol.md",
        "plan_ref": "plans/resilience-and-safety.md",
        "ac_ids": ["AC-60.01"],
    }
    by_file = {"60-crisis-safety-protocol.md": {"status": "📝 Draft"}}
    by_num = {"S60": [{"file": "60-crisis-safety-protocol.md"}]}

    result = queue_gate_module.classify_item(item, by_file, by_num)

    assert result.readiness == "SPEC_POLISH_REQUIRED"
    assert result.recommended_lane == "SPEC_POLISH"
    assert result.human_gate_required is True


def test_duplicate_spec_id_blocks_routing(queue_gate_module):
    item = {
        "id": "FB-DUP",
        "title": "Ambiguous item",
        "spec_ref": "specs/50-concurrent-universe-loading.md",
        "plan_ref": "plans/world-and-genesis.md",
        "ac_ids": ["AC-50.01"],
    }
    by_file = {"50-concurrent-universe-loading.md": {"status": "✅ Approved"}}
    by_num = {
        "S50": [
            {"file": "50-concurrent-universe-loading.md"},
            {"file": "50-rate-limit-budget.md"},
        ]
    }

    result = queue_gate_module.classify_item(item, by_file, by_num)

    assert result.readiness == "INVALID_UNTIL_SPEC_ID_FIXED"
    assert result.recommended_lane == "INVALID_UNTIL_SPEC_ID_FIXED"
    assert result.human_gate_required is True


def test_bounded_approved_ac_gap_routes_to_implement(queue_gate_module):
    item = {
        "id": "FB-READY",
        "title": "Redis pooling",
        "spec_ref": "specs/28-performance-and-scaling.md",
        "plan_ref": "plans/system.md",
        "ac_ids": ["AC-28.08"],
    }
    by_file = {"28-performance-and-scaling.md": {"status": "✅ Approved"}}
    by_num = {"S28": [{"file": "28-performance-and-scaling.md"}]}

    result = queue_gate_module.classify_item(item, by_file, by_num)

    assert result.readiness == queue_gate_module.IMPLEMENT_READY
    assert result.recommended_lane == "IMPLEMENT"
    assert result.validation_command == "make gate"
    assert result.human_gate_required is False
