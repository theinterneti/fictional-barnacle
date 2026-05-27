#!/usr/bin/env python3
"""Developer workflow entrypoint for deterministic local feedback.

Make remains the public interface; this module owns the logic behind fast local
status, changed-test selection, and fail-fast changed-file gates.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from changed_tests import changed_files_from_git, plan_for_changed_files  # noqa: E402

REQUIRED_TOOLS = ("uv", "git")
OPTIONAL_TOOLS = ("docker", "gh", "jq")


@dataclass(frozen=True)
class DoctorReport:
    required_present: list[str] = field(default_factory=list)
    required_missing: list[str] = field(default_factory=list)
    optional_present: list[str] = field(default_factory=list)
    optional_missing: list[str] = field(default_factory=list)

    @property
    def required_ok(self) -> bool:
        return not self.required_missing

    @property
    def exit_code(self) -> int:
        return 0 if self.required_ok else 1


@dataclass(frozen=True)
class RepoSnapshot:
    branch: str
    ahead_behind: str
    dirty_files: list[str]
    approved_trace: str
    queue_ready: int
    queue_blockers: int


def build_doctor_report(which: Callable[[str], bool] | None = None) -> DoctorReport:
    checker = which or (lambda name: shutil.which(name) is not None)
    required_present: list[str] = []
    required_missing: list[str] = []
    optional_present: list[str] = []
    optional_missing: list[str] = []

    for tool in REQUIRED_TOOLS:
        (required_present if checker(tool) else required_missing).append(tool)
    for tool in OPTIONAL_TOOLS:
        (optional_present if checker(tool) else optional_missing).append(tool)

    return DoctorReport(
        required_present=required_present,
        required_missing=required_missing,
        optional_present=optional_present,
        optional_missing=optional_missing,
    )


def render_doctor(report: DoctorReport) -> str:
    lines = ["Developer doctor", "================"]
    lines.append("required_present: " + (", ".join(report.required_present) or "none"))
    lines.append("required_missing: " + (", ".join(report.required_missing) or "none"))
    lines.append("optional_present: " + (", ".join(report.optional_present) or "none"))
    lines.append("optional_missing: " + (", ".join(report.optional_missing) or "none"))
    lines.append(f"required_ok: {report.required_ok}")
    return "\n".join(lines)


def gate_changed_commands(paths: Iterable[str]) -> list[str]:
    return plan_for_changed_files(paths).validation_commands()


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


def collect_snapshot() -> RepoSnapshot:
    branch = _git_output(["branch", "--show-current"]) or "DETACHED"
    status_lines = _git_output(["status", "--short", "--branch"]).splitlines()
    ahead_behind = _parse_ahead_behind(status_lines[0] if status_lines else "")
    dirty_files = [line[3:] for line in status_lines[1:] if len(line) > 3]
    approved_trace = _trace_headline()
    queue_ready, queue_blockers = _queue_summary()
    return RepoSnapshot(
        branch=branch,
        ahead_behind=ahead_behind,
        dirty_files=dirty_files,
        approved_trace=approved_trace,
        queue_ready=queue_ready,
        queue_blockers=queue_blockers,
    )


def _git_output(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _parse_ahead_behind(header: str) -> str:
    if "[" not in header or "]" not in header:
        return "even"
    return header.split("[", 1)[1].split("]", 1)[0]


def _trace_headline() -> str:
    result = subprocess.run(
        ["uv", "run", "python", "specs/trace_acs.py", "--validate"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    for line in result.stdout.splitlines():
        if "Approved (headline):" in line:
            # Example: ✅ Approved (headline): 343/343 → 100.0%
            parts = line.split("Approved (headline):", 1)[1].strip().split()
            return parts[0] if parts else "unknown"
    return "unknown"


def _queue_summary() -> tuple[int, int]:
    result = subprocess.run(
        ["uv", "run", "python", "scripts/queue_readiness_gate.py", "--json"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return 0, 0
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return 0, 0
    return int(payload.get("implement_ready_count", 0)), int(
        payload.get("governance_blocker_count", 0)
    )


def render_status(snapshot: RepoSnapshot) -> str:
    lines = ["Repo status", "==========="]
    lines.append(f"branch: {snapshot.branch}")
    lines.append(f"ahead_behind: {snapshot.ahead_behind}")
    lines.append("dirty_files: " + (", ".join(snapshot.dirty_files) or "none"))
    lines.append(f"approved_trace: {snapshot.approved_trace}")
    lines.append(f"queue_ready: {snapshot.queue_ready}")
    lines.append(f"queue_blockers: {snapshot.queue_blockers}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic fictional-barnacle workflow helper."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check local workflow prerequisites")
    sub.add_parser("status", help="Print compact repo workflow status")
    gate = sub.add_parser("gate-changed", help="Run the changed-file verifier set")
    gate.add_argument(
        "paths", nargs="*", help="Changed paths. Defaults to git diff discovery."
    )
    gate.add_argument("--base-ref", default="origin/main")
    args = parser.parse_args()

    if args.command == "doctor":
        report = build_doctor_report()
        print(render_doctor(report))
        return report.exit_code
    if args.command == "status":
        print(render_status(collect_snapshot()))
        return 0
    if args.command == "gate-changed":
        paths = args.paths or changed_files_from_git(args.base_ref)
        return run_commands(gate_changed_commands(paths))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
