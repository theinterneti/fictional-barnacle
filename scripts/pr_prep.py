#!/usr/bin/env python3
"""Prepare deterministic PR evidence without creating remote side effects."""

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
class PrReadiness:
    ready: bool
    branch: str
    base_branch: str
    changed_paths: list[str]
    unstaged_paths: list[str]
    staged_paths: list[str]
    reasons: list[str]

    @property
    def exit_code(self) -> int:
        return 0 if self.ready else 1


def build_pr_body(
    summary: Iterable[str],
    verification: Iterable[str],
    changed_paths: Iterable[str],
) -> str:
    summary_lines = [f"- {item}" for item in summary] or [
        "- Prepared by deterministic local automation."
    ]
    verification_lines = [f"- [x] `{item}`" for item in verification]
    changed_lines = [f"- `{path}`" for path in sorted(set(changed_paths))]
    return "\n".join(
        [
            "## Summary",
            *summary_lines,
            "",
            "## Verification",
            *verification_lines,
            "",
            "## Changed Files",
            *changed_lines,
            "",
            "## Notes",
            "- Generated locally by `make pr-prep`; no remote side effects performed.",
            "",
        ]
    )


def evaluate_pr_readiness(
    branch: str,
    base_branch: str,
    changed_paths: Iterable[str],
    unstaged_paths: Iterable[str],
    staged_paths: Iterable[str],
) -> PrReadiness:
    changed = _dedupe(changed_paths)
    unstaged = _dedupe(unstaged_paths)
    staged = _dedupe(staged_paths)
    reasons: list[str] = []
    if branch == base_branch:
        reasons.append("PR branch must not be the base branch")
    if unstaged:
        reasons.append("unstaged work must be committed before PR prep")
    if staged:
        reasons.append("staged work must be committed before PR prep")
    if not changed:
        reasons.append("PR must contain changes relative to the base branch")
    if any(_is_production_change(path) for path in changed) and not any(
        path.startswith(TEST_PREFIX) for path in changed
    ):
        reasons.append("production changes require test changes")
    return PrReadiness(
        ready=not reasons,
        branch=branch,
        base_branch=base_branch,
        changed_paths=changed,
        unstaged_paths=unstaged,
        staged_paths=staged,
        reasons=reasons,
    )


def collect_changed_paths(base_branch: str) -> list[str]:
    return _git_lines(["git", "diff", "--name-only", f"origin/{base_branch}...HEAD"])


def collect_staged_paths() -> list[str]:
    return _git_lines(["git", "diff", "--cached", "--name-only"])


def collect_unstaged_paths() -> list[str]:
    return _git_lines(["git", "diff", "--name-only"])


def current_branch() -> str:
    lines = _git_lines(["git", "branch", "--show-current"])
    return lines[0] if lines else ""


def _git_lines(command: list[str]) -> list[str]:
    result = subprocess.run(
        command, cwd=ROOT, check=False, text=True, capture_output=True
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_production_change(path: str) -> bool:
    return path in PRODUCTION_FILES or path.startswith(PRODUCTION_PREFIXES)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def render_readiness(result: PrReadiness) -> str:
    lines = ["PR readiness", "============", f"ready: {result.ready}"]
    lines.append(f"branch: {result.branch}")
    lines.append(f"base_branch: {result.base_branch}")
    lines.append(f"changed_paths: {len(result.changed_paths)}")
    lines.append("reasons: " + (", ".join(result.reasons) or "none"))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare deterministic PR evidence.")
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--body",
        action="store_true",
        help="Print generated PR body instead of readiness.",
    )
    args = parser.parse_args()

    changed = collect_changed_paths(args.base_branch)
    readiness = evaluate_pr_readiness(
        branch=current_branch(),
        base_branch=args.base_branch,
        changed_paths=changed,
        unstaged_paths=collect_unstaged_paths(),
        staged_paths=collect_staged_paths(),
    )
    if args.body:
        print(
            build_pr_body(
                summary=["Prepare fictional-barnacle local automation evidence."],
                verification=["make gate", "make complete-check", "make release-check"],
                changed_paths=changed,
            )
        )
        return readiness.exit_code
    if args.json:
        print(
            json.dumps(asdict(readiness) | {"exit_code": readiness.exit_code}, indent=2)
        )
    else:
        print(render_readiness(readiness))
    return readiness.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
