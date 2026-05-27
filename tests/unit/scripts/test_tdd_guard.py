from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def tdd_module():
    path = Path("scripts/tdd_guard.py")
    spec = importlib.util.spec_from_file_location("tdd_guard", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_source_change_without_test_change_fails(tdd_module) -> None:
    result = tdd_module.evaluate_tdd_evidence(["src/tta/api/app.py"])

    assert result.production_changed is True
    assert result.test_changed is False
    assert result.exit_code == 1


def test_source_change_with_test_change_passes(tdd_module) -> None:
    result = tdd_module.evaluate_tdd_evidence(
        ["src/tta/api/app.py", "tests/unit/api/test_app.py"]
    )

    assert result.production_changed is True
    assert result.test_changed is True
    assert result.exit_code == 0


def test_tooling_change_with_script_test_passes(tdd_module) -> None:
    result = tdd_module.evaluate_tdd_evidence(
        ["scripts/workflow_state.py", "tests/unit/scripts/test_workflow_state.py"]
    )

    assert result.production_changed is True
    assert result.test_changed is True
    assert result.exit_code == 0


def test_docs_only_change_does_not_require_tdd(tdd_module) -> None:
    result = tdd_module.evaluate_tdd_evidence(["docs/release.md"])

    assert result.production_changed is False
    assert result.exit_code == 0
