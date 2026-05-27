from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def dev_workflow_module():
    path = Path("scripts/dev_workflow.py")
    spec = importlib.util.spec_from_file_location("dev_workflow", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.spec("AC-65.04")
def test_doctor_reports_missing_required_tools(dev_workflow_module) -> None:
    availability = {"uv": True, "git": True, "docker": False, "gh": False, "jq": True}

    report = dev_workflow_module.build_doctor_report(lambda name: availability[name])

    assert report.required_ok is True
    assert "docker" in report.optional_missing
    assert "gh" in report.optional_missing
    assert report.exit_code == 0


@pytest.mark.spec("AC-65.01")
def test_gate_changed_commands_use_changed_test_plan(dev_workflow_module) -> None:
    commands = dev_workflow_module.gate_changed_commands(
        ["src/tta/prompts/loader.py", "specs/09-prompt-and-content.md"]
    )

    assert commands[0].startswith("uv run ruff format --check")
    assert "uv run pytest tests/unit/prompts -q" in commands
    assert "make trace" in commands
    assert "uv run python specs/index_specs.py --validate" in commands


@pytest.mark.spec("AC-65.02")
def test_gate_changed_short_circuits_when_command_fails(dev_workflow_module) -> None:
    calls: list[str] = []

    def fake_run(command: str) -> int:
        calls.append(command)
        return 7 if command == "second" else 0

    exit_code = dev_workflow_module.run_commands(["first", "second", "third"], fake_run)

    assert exit_code == 7
    assert calls == ["first", "second"]


@pytest.mark.spec("AC-65.04")
def test_status_report_includes_branch_trace_and_queue(dev_workflow_module) -> None:
    snapshot = dev_workflow_module.RepoSnapshot(
        branch="main",
        ahead_behind="ahead 1",
        dirty_files=["scripts/dev_workflow.py"],
        approved_trace="343/343",
        queue_ready=2,
        queue_blockers=0,
    )

    report = dev_workflow_module.render_status(snapshot)

    assert "branch: main" in report
    assert "ahead 1" in report
    assert "approved_trace: 343/343" in report
    assert "queue_ready: 2" in report
