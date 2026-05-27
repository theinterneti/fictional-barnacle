from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def changed_tests_module():
    path = Path("scripts/changed_tests.py")
    spec = importlib.util.spec_from_file_location("changed_tests", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.spec("AC-65.01")
def test_moderation_source_change_selects_moderation_unit_tests(
    changed_tests_module,
) -> None:
    plan = changed_tests_module.plan_for_changed_files(["src/tta/moderation/hook.py"])

    assert "tests/unit/moderation" in plan.pytest_targets
    assert "src/tta/moderation/hook.py" in plan.ruff_targets
    assert plan.integration_recommended is False


@pytest.mark.spec("AC-65.01")
def test_spec_change_runs_trace_and_spec_validator(changed_tests_module) -> None:
    plan = changed_tests_module.plan_for_changed_files(["specs/65-local-ci-gate.md"])

    assert "make trace" in plan.extra_commands
    assert "uv run python specs/index_specs.py --validate" in plan.extra_commands
    assert plan.validation_commands()[0] == "make trace"


@pytest.mark.spec("AC-65.01")
def test_prompt_template_change_selects_prompt_unit_tests(changed_tests_module) -> None:
    plan = changed_tests_module.plan_for_changed_files(
        ["prompts/templates/narrative/generate.prompt.md"]
    )

    assert "tests/unit/prompts" in plan.pytest_targets
    assert "make trace" in plan.extra_commands


@pytest.mark.spec("AC-65.02")
def test_integration_change_recommends_full_gate(changed_tests_module) -> None:
    plan = changed_tests_module.plan_for_changed_files(
        ["tests/integration/test_s12_persistence_integration.py"]
    )

    assert plan.integration_recommended is True
    assert "make gate-full" in "\n".join(plan.summary_lines())


@pytest.mark.spec("AC-65.04")
def test_text_report_is_discoverable_and_deterministic(changed_tests_module) -> None:
    plan = changed_tests_module.plan_for_changed_files(
        ["src/tta/api/routes/games_stream.py", "plans/ops.md"]
    )

    report = changed_tests_module.render_text_report(plan)

    assert "Changed-test plan" in report
    assert "tests/unit/api" in report
    assert "uv run python plans/index_plans.py --validate" in report


@pytest.mark.spec("AC-65.01")
def test_changed_files_from_git_avoids_expensive_untracked_scan(
    changed_tests_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""

    def fake_run(command, **_kwargs):
        commands.append(command)
        return Result()

    monkeypatch.setattr(changed_tests_module.subprocess, "run", fake_run)

    changed_tests_module.changed_files_from_git("origin/main")

    assert ["git", "ls-files", "--others", "--exclude-standard"] not in commands
    assert commands == [
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
    ]
