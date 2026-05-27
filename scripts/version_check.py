#!/usr/bin/env python3
"""Validate project version metadata and release changelog sections."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$"
)
VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


@dataclass(frozen=True)
class VersionResult:
    version: str
    semver_ok: bool
    changelog_section_exists: bool
    require_changelog_section: bool
    reason: str

    @property
    def exit_code(self) -> int:
        if not self.semver_ok:
            return 1
        if self.require_changelog_section and not self.changelog_section_exists:
            return 1
        return 0


def evaluate_version(
    *,
    pyproject_text: str,
    changelog_text: str,
    require_changelog_section: bool,
) -> VersionResult:
    version = extract_version(pyproject_text)
    semver_ok = bool(SEMVER_RE.match(version))
    section_exists = bool(
        version
        and re.search(rf"^## \[{re.escape(version)}\]", changelog_text, re.MULTILINE)
    )
    if not semver_ok:
        reason = "pyproject version must be SemVer (MAJOR.MINOR.PATCH)."
    elif require_changelog_section and not section_exists:
        reason = f"CHANGELOG.md must contain a ## [{version}] release section."
    else:
        reason = "Version metadata is release-ready."
    return VersionResult(
        version=version,
        semver_ok=semver_ok,
        changelog_section_exists=section_exists,
        require_changelog_section=require_changelog_section,
        reason=reason,
    )


def extract_version(pyproject_text: str) -> str:
    match = VERSION_RE.search(pyproject_text)
    return match.group(1) if match else ""


def render_result(result: VersionResult) -> str:
    lines = ["Version check", "============="]
    lines.append(f"version: {result.version or 'missing'}")
    lines.append(f"semver_ok: {result.semver_ok}")
    lines.append(f"require_changelog_section: {result.require_changelog_section}")
    lines.append(f"changelog_section_exists: {result.changelog_section_exists}")
    lines.append(f"reason: {result.reason}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate version/release metadata.")
    parser.add_argument(
        "--release",
        action="store_true",
        help="Require CHANGELOG.md to contain a section for the current version.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = evaluate_version(
        pyproject_text=PYPROJECT.read_text(encoding="utf-8"),
        changelog_text=CHANGELOG.read_text(encoding="utf-8")
        if CHANGELOG.exists()
        else "",
        require_changelog_section=args.release,
    )
    if args.json:
        print(json.dumps(asdict(result) | {"exit_code": result.exit_code}, indent=2))
    else:
        print(render_result(result))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
