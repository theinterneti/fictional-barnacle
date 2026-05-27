from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.spec("AC-65.04")
def test_phase1_developer_targets_are_documented() -> None:
    makefile = Path("Makefile").read_text()

    expected_targets = {
        "doctor": "Check local developer workflow prerequisites",
        "status": "Show deterministic repo workflow status",
        "changed-tests": "Plan targeted checks for changed files",
        "gate-changed": "Run targeted changed-file local gate",
    }
    for target, description in expected_targets.items():
        assert f"{target}:" in makefile
        assert description in makefile


@pytest.mark.spec("AC-65.03")
def test_gate_full_runs_gate_before_integration() -> None:
    makefile = Path("Makefile").read_text()

    assert "gate-full: gate test-integration" in makefile


@pytest.mark.spec("AC-65.01")
def test_test_unit_target_is_path_scoped_to_non_service_tests() -> None:
    makefile = Path("Makefile").read_text()

    assert (
        'uv run pytest tests/unit tests/bdd -m "not integration and not e2e"'
        in makefile
    )


def test_phase2_release_targets_are_documented() -> None:
    makefile = Path("Makefile").read_text()

    expected_targets = {
        "changelog-check": "Validate unreleased changelog coverage for changed files",
        "version-check": "Validate pyproject version and release changelog section",
        "release-check": "Run release readiness checks without mutating state",
        "release-dry-run": "Preview release gate and current version metadata",
    }
    for target, description in expected_targets.items():
        assert f"{target}:" in makefile
        assert description in makefile


def test_phase3_workflow_targets_are_documented() -> None:
    makefile = Path("Makefile").read_text()

    expected_targets = {
        "work-status": "Show SDD work-item state summary",
        "work-next": "Show the next non-terminal SDD work item",
        "work-advance": "Advance a work item after deterministic evidence is present",
    }
    for target, description in expected_targets.items():
        assert f"{target}:" in makefile
        assert description in makefile
