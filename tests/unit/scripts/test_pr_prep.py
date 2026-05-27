from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def pr_prep_module():
    path = Path("scripts/pr_prep.py")
    spec = importlib.util.spec_from_file_location("pr_prep", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_pr_body_includes_summary_and_verification(pr_prep_module) -> None:
    body = pr_prep_module.build_pr_body(
        summary=["Add deterministic PR preparation"],
        verification=["make gate", "make release-check"],
        changed_paths=["scripts/pr_prep.py", "tests/unit/scripts/test_pr_prep.py"],
    )

    assert "## Summary" in body
    assert "- Add deterministic PR preparation" in body
    assert "## Verification" in body
    assert "- [x] `make gate`" in body
    assert "- [x] `make release-check`" in body
    assert "scripts/pr_prep.py" in body


def test_readiness_fails_on_dirty_unstaged_work(pr_prep_module) -> None:
    result = pr_prep_module.evaluate_pr_readiness(
        branch="feat/local-automation",
        base_branch="main",
        changed_paths=["scripts/pr_prep.py", "tests/unit/scripts/test_pr_prep.py"],
        unstaged_paths=["scripts/pr_prep.py"],
        staged_paths=[],
    )

    assert result.ready is False
    assert result.exit_code == 1
    assert "unstaged work must be committed before PR prep" in result.reasons


def test_readiness_requires_non_main_branch(pr_prep_module) -> None:
    result = pr_prep_module.evaluate_pr_readiness(
        branch="main",
        base_branch="main",
        changed_paths=["scripts/pr_prep.py", "tests/unit/scripts/test_pr_prep.py"],
        unstaged_paths=[],
        staged_paths=[],
    )

    assert result.ready is False
    assert "PR branch must not be the base branch" in result.reasons


def test_readiness_requires_tests_for_production_changes(pr_prep_module) -> None:
    result = pr_prep_module.evaluate_pr_readiness(
        branch="feat/local-automation",
        base_branch="main",
        changed_paths=["scripts/pr_prep.py"],
        unstaged_paths=[],
        staged_paths=[],
    )

    assert result.ready is False
    assert "production changes require test changes" in result.reasons
