from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def completion_module():
    path = Path("scripts/completion_check.py")
    spec = importlib.util.spec_from_file_location("completion_check", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_completion_commands_are_deterministic(completion_module) -> None:
    commands = completion_module.completion_commands()

    assert commands == [
        "make gate-changed",
        "make tdd-check",
        "make changelog-check",
        "make trace",
    ]


def test_run_commands_stops_on_first_failure(completion_module) -> None:
    calls: list[str] = []

    def fake_run(command: str) -> int:
        calls.append(command)
        return 4 if command == "make tdd-check" else 0

    exit_code = completion_module.run_commands(
        completion_module.completion_commands(), fake_run
    )

    assert exit_code == 4
    assert calls == ["make gate-changed", "make tdd-check"]
