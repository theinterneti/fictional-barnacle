#!/usr/bin/env python3
"""Completion gate that composes deterministic local checks."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def completion_commands() -> list[str]:
    return [
        "make gate-changed",
        "make tdd-check",
        "make changelog-check",
        "make trace",
    ]


def run_commands(
    commands: Iterable[str],
    runner: Callable[[str], int] | None = None,
) -> int:
    run = runner or _run_shell_command
    for command in commands:
        print(f"\n$ {command}", flush=True)
        exit_code = run(command)
        if exit_code != 0:
            return exit_code
    return 0


def _run_shell_command(command: str) -> int:
    return subprocess.run(command, cwd=ROOT, shell=True, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic completion checks.")
    parser.parse_args()
    return run_commands(completion_commands())


if __name__ == "__main__":
    raise SystemExit(main())
