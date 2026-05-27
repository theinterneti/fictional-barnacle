#!/usr/bin/env python3
"""Plan deterministic checks for the currently changed files.

This script is intentionally conservative: it does not try to prove that a
small target set is sufficient for merge. It gives agents and developers a fast,
repeatable first verifier set before escalating to ``make gate``.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PYTHON_SUFFIXES = {".py"}
RUFF_SUFFIXES = {".py"}
PROMPT_PREFIXES = ("prompts/", "src/tta/prompts/")
SPEC_PREFIX = "specs/"
PLAN_PREFIX = "plans/"
INTEGRATION_PREFIX = "tests/integration/"


@dataclass(frozen=True)
class ChangedTestPlan:
    changed_files: list[str]
    ruff_targets: list[str] = field(default_factory=list)
    pytest_targets: list[str] = field(default_factory=list)
    extra_commands: list[str] = field(default_factory=list)
    integration_recommended: bool = False
    practical_gate_recommended: bool = False
    reasons: list[str] = field(default_factory=list)

    def validation_commands(self) -> list[str]:
        commands: list[str] = []
        if self.ruff_targets:
            quoted = " ".join(shlex.quote(path) for path in self.ruff_targets)
            commands.append(f"uv run ruff format --check {quoted}")
            commands.append(f"uv run ruff check {quoted}")
        commands.extend(self.extra_commands)
        if self.pytest_targets:
            quoted_tests = " ".join(shlex.quote(path) for path in self.pytest_targets)
            commands.append(f"uv run pytest {quoted_tests} -q")
        if self.integration_recommended:
            commands.append("make gate-full")
        elif not commands:
            commands.append("make trace")
        return _dedupe(commands)

    def summary_lines(self) -> list[str]:
        lines = [
            f"changed_files: {len(self.changed_files)}",
            "ruff_targets: " + (", ".join(self.ruff_targets) or "none"),
            "pytest_targets: " + (", ".join(self.pytest_targets) or "none"),
            "extra_commands: " + (", ".join(self.extra_commands) or "none"),
            f"integration_recommended: {self.integration_recommended}",
            f"practical_gate_recommended: {self.practical_gate_recommended}",
        ]
        if self.integration_recommended:
            lines.append("recommended_full_gate: make gate-full")
        if self.reasons:
            lines.append("reasons: " + "; ".join(self.reasons))
        return lines


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def changed_files_from_git(base_ref: str = "origin/main") -> list[str]:
    """Return committed diff plus unstaged/staged dirt.

    Deliberately avoid a full untracked-file scan here. On large worktrees or
    repos with generated local artifacts, `git ls-files --others` can dominate
    the feedback loop or hang. This gate is intended for committed/staged work;
    new files are covered once staged or committed.
    """
    commands = [
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
    ]
    paths: list[str] = []
    for command in commands:
        result = subprocess.run(  # noqa: S603 - fixed git argv, no shell
            command,
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            paths.extend(line.strip() for line in result.stdout.splitlines())
    return _dedupe(path for path in paths if path)


def _add_pytest(targets: list[str], target: str) -> None:
    if (ROOT / target).exists() and target not in targets:
        targets.append(target)


def plan_for_changed_files(paths: Iterable[str]) -> ChangedTestPlan:
    changed = _dedupe(str(Path(path).as_posix()) for path in paths if str(path).strip())
    ruff_targets: list[str] = []
    pytest_targets: list[str] = []
    extra_commands: list[str] = []
    reasons: list[str] = []
    integration_recommended = False
    practical_gate_recommended = False

    for path in changed:
        suffix = Path(path).suffix
        if suffix in RUFF_SUFFIXES:
            ruff_targets.append(path)

        if path.startswith("tests/unit/") and suffix == ".py":
            _add_pytest(pytest_targets, path)
        elif path.startswith("src/tta/moderation/"):
            _add_pytest(pytest_targets, "tests/unit/moderation")
            reasons.append("moderation source changed")
        elif path.startswith(PROMPT_PREFIXES) or path.startswith("prompts/"):
            _add_pytest(pytest_targets, "tests/unit/prompts")
            _add_command(extra_commands, "make trace")
            reasons.append("prompt contract changed")
        elif path.startswith("src/tta/api/"):
            _add_pytest(pytest_targets, "tests/unit/api")
            practical_gate_recommended = True
            reasons.append("API boundary changed")
        elif path.startswith("src/tta/persistence/") or path.startswith("migrations/"):
            _add_pytest(pytest_targets, "tests/unit/persistence")
            _add_pytest(pytest_targets, "tests/unit/test_migration_014.py")
            integration_recommended = True
            reasons.append("persistence or migration boundary changed")
        elif path.startswith("src/tta/pipeline/"):
            _add_pytest(pytest_targets, "tests/unit/pipeline")
            reasons.append("turn pipeline changed")
        elif path.startswith("src/tta/llm/"):
            _add_pytest(pytest_targets, "tests/unit/llm")
            practical_gate_recommended = True
            reasons.append("LLM routing boundary changed")
        elif path.startswith("src/tta/eval/"):
            _add_pytest(pytest_targets, "tests/unit/eval")
            practical_gate_recommended = True
            reasons.append("evaluation boundary changed")
        elif path.startswith(INTEGRATION_PREFIX):
            _add_pytest(pytest_targets, path)
            integration_recommended = True
            reasons.append("integration test changed")
        elif path.startswith(SPEC_PREFIX):
            _add_command(extra_commands, "make trace")
            _add_command(
                extra_commands, "uv run python specs/index_specs.py --validate"
            )
            reasons.append("spec changed")
        elif path.startswith(PLAN_PREFIX):
            _add_command(
                extra_commands, "uv run python plans/index_plans.py --validate"
            )
            reasons.append("plan changed")
        elif path == "Makefile" or path.startswith("scripts/"):
            _add_pytest(pytest_targets, "tests/unit/scripts")
            reasons.append("developer tooling changed")
        elif suffix == ".py":
            _add_pytest(pytest_targets, "tests/unit")
            reasons.append("unclassified Python changed")

    return ChangedTestPlan(
        changed_files=changed,
        ruff_targets=_dedupe(ruff_targets),
        pytest_targets=_dedupe(pytest_targets),
        extra_commands=_dedupe(extra_commands),
        integration_recommended=integration_recommended,
        practical_gate_recommended=practical_gate_recommended,
        reasons=_dedupe(reasons),
    )


def _add_command(commands: list[str], command: str) -> None:
    if command not in commands:
        commands.append(command)


def render_text_report(plan: ChangedTestPlan) -> str:
    lines = ["Changed-test plan", "================="]
    lines.extend(plan.summary_lines())
    lines.append("")
    lines.append("commands:")
    lines.extend(f"  {command}" for command in plan.validation_commands())
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan deterministic checks for changed files."
    )
    parser.add_argument(
        "paths", nargs="*", help="Changed paths. Defaults to git diff discovery."
    )
    parser.add_argument(
        "--base-ref", default="origin/main", help="Git base ref for HEAD diff"
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    paths = args.paths or changed_files_from_git(args.base_ref)
    plan = plan_for_changed_files(paths)
    if args.json:
        print(
            json.dumps(
                asdict(plan) | {"commands": plan.validation_commands()}, indent=2
            )
        )
    else:
        print(render_text_report(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
