#!/usr/bin/env python3
"""Validate changelog coverage for release-relevant local changes."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
RELEASE_RELEVANT_PREFIXES = (
    "src/",
    "scripts/",
    "specs/",
    "plans/",
    "prompts/",
    "migrations/",
    "tests/",
)
RELEASE_RELEVANT_FILES = {"Makefile", "pyproject.toml", "uv.lock"}
PLACEHOLDERS = {"tbd", "todo", "none", "n/a", "placeholder"}


@dataclass(frozen=True)
class ChangelogResult:
    release_note_required: bool
    has_unreleased_entry: bool
    changed_paths: list[str]
    reason: str

    @property
    def exit_code(self) -> int:
        return 0 if (not self.release_note_required or self.has_unreleased_entry) else 1


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
            command,
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            paths.extend(
                line.strip() for line in result.stdout.splitlines() if line.strip()
            )
    return _dedupe(paths)


def evaluate_changelog(
    changelog_text: str, changed_paths: Iterable[str]
) -> ChangelogResult:
    paths = _dedupe(path for path in changed_paths if path)
    required = any(is_release_relevant(path) for path in paths)
    has_entry = has_unreleased_entry(changelog_text)
    if not required:
        reason = "Only documentation or non-release metadata changed."
    elif has_entry:
        reason = "Release-relevant changes have an Unreleased changelog entry."
    else:
        reason = "Release-relevant changes require a non-placeholder Unreleased entry."
    return ChangelogResult(
        release_note_required=required,
        has_unreleased_entry=has_entry,
        changed_paths=paths,
        reason=reason,
    )


def is_release_relevant(path: str) -> bool:
    if path == "CHANGELOG.md" or path.startswith("docs/"):
        return False
    return path in RELEASE_RELEVANT_FILES or path.startswith(RELEASE_RELEVANT_PREFIXES)


def has_unreleased_entry(changelog_text: str) -> bool:
    section = _section(changelog_text, "Unreleased")
    if not section:
        return False
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        item = stripped[2:].strip().lower().strip(".")
        if item and item not in PLACEHOLDERS:
            return True
    return False


def _section(markdown: str, heading: str) -> str:
    pattern = re.compile(rf"^## \[{re.escape(heading)}\].*$", re.MULTILINE)
    match = pattern.search(markdown)
    if not match:
        return ""
    next_match = re.search(r"^## ", markdown[match.end() :], re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(markdown)
    return markdown[match.end() : end]


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def render_result(result: ChangelogResult) -> str:
    lines = ["Changelog check", "==============="]
    lines.append(f"release_note_required: {result.release_note_required}")
    lines.append(f"has_unreleased_entry: {result.has_unreleased_entry}")
    lines.append(f"changed_paths: {len(result.changed_paths)}")
    lines.append(f"reason: {result.reason}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate CHANGELOG.md coverage.")
    parser.add_argument(
        "paths", nargs="*", help="Changed paths. Defaults to git discovery."
    )
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paths = args.paths or changed_files_from_git(args.base_ref)
    text = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else ""
    result = evaluate_changelog(text, paths)
    if args.json:
        print(json.dumps(asdict(result) | {"exit_code": result.exit_code}, indent=2))
    else:
        print(render_result(result))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
