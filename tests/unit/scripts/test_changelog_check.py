from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def changelog_module():
    path = Path("scripts/changelog_check.py")
    spec = importlib.util.spec_from_file_location("changelog_check", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_source_change_requires_unreleased_changelog_entry(changelog_module) -> None:
    changelog = "# Changelog\n\n## [Unreleased]\n\n### Added\n"

    result = changelog_module.evaluate_changelog(
        changelog,
        changed_paths=["src/tta/api/app.py"],
    )

    assert result.release_note_required is True
    assert result.has_unreleased_entry is False
    assert result.exit_code == 1


def test_unreleased_bullet_satisfies_required_change(changelog_module) -> None:
    changelog = (
        "# Changelog\n\n## [Unreleased]\n\n### Changed\n- Add local gate automation.\n"
    )

    result = changelog_module.evaluate_changelog(
        changelog,
        changed_paths=["scripts/dev_workflow.py"],
    )

    assert result.release_note_required is True
    assert result.has_unreleased_entry is True
    assert result.exit_code == 0


def test_docs_only_change_does_not_require_changelog(changelog_module) -> None:
    changelog = "# Changelog\n\n## [Unreleased]\n"

    result = changelog_module.evaluate_changelog(
        changelog,
        changed_paths=["docs/release.md"],
    )

    assert result.release_note_required is False
    assert result.exit_code == 0


def test_placeholder_bullets_do_not_count(changelog_module) -> None:
    changelog = "# Changelog\n\n## [Unreleased]\n\n### Fixed\n- TBD\n"

    result = changelog_module.evaluate_changelog(
        changelog,
        changed_paths=["Makefile"],
    )

    assert result.has_unreleased_entry is False
    assert result.exit_code == 1
