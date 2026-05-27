#!/usr/bin/env python3
"""Deterministic TDD evidence guard for changed files."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_PREFIXES = ("src/", "scripts/", "migrations/", "prompts/")
PRODUCTION_FILES = {"Makefile", "pyproject.toml"}
TEST_PREFIX = "tests/"


@dataclass(frozen=True)
class TddResult:
    production_changed: bool
    test_changed: bool
    changed_paths: list[str]
    reason: str

    @property
    def exit_code(self) -> int:
        return 0 if (not self.production_changed or self.test_changed) else 1


def changed_files_from_git(base_ref: str = "origin/main") -> list[str]:
    commands = [
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    paths: list[str] = []
    for command in commands:
        result = subprocess.run(
            command, cwd=ROOT, check=False, text=True, capture_output=True
        )
        if result.returncode == 0:
            paths.extend(
                line.strip() for line in result.stdout.splitlines() if line.strip()
            )
    return _dedupe(paths)


def evaluate_tdd_evidence(paths: Iterable[str]) -> TddResult:
    changed = _dedupe(path for path in paths if path)
    production_changed = any(is_production_change(path) for path in changed)
    test_changed = any(path.startswith(TEST_PREFIX) for path in changed)
    if not production_changed:
        reason = "No production/tooling change requires TDD evidence."
    elif test_changed:
        reason = "Production/tooling changes include test evidence."
    else:
        reason = "Production/tooling changes require a corresponding test change."
    return TddResult(
        production_changed=production_changed,
        test_changed=test_changed,
        changed_paths=changed,
        reason=reason,
    )


def is_production_change(path: str) -> bool:
    return path in PRODUCTION_FILES or path.startswith(PRODUCTION_PREFIXES)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def render_result(result: TddResult) -> str:
    return "\n".join(
        [
            "TDD guard",
            "=========",
            f"production_changed: {result.production_changed}",
            f"test_changed: {result.test_changed}",
            f"changed_paths: {len(result.changed_paths)}",
            f"reason: {result.reason}",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate TDD evidence for changed files."
    )
    parser.add_argument(
        "paths", nargs="*", help="Changed paths. Defaults to git discovery."
    )
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = evaluate_tdd_evidence(args.paths or changed_files_from_git(args.base_ref))
    if args.json:
        print(json.dumps(asdict(result) | {"exit_code": result.exit_code}, indent=2))
    else:
        print(render_result(result))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
