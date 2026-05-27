from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def version_module():
    path = Path("scripts/version_check.py")
    spec = importlib.util.spec_from_file_location("version_check", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_pyproject_version_must_be_semver(version_module) -> None:
    result = version_module.evaluate_version(
        pyproject_text='[project]\nversion = "0.2.0"\n',
        changelog_text="# Changelog\n\n## [0.2.0] - 2026-05-27\n",
        require_changelog_section=True,
    )

    assert result.version == "0.2.0"
    assert result.semver_ok is True
    assert result.changelog_section_exists is True
    assert result.exit_code == 0


def test_release_check_fails_without_matching_changelog_section(version_module) -> None:
    result = version_module.evaluate_version(
        pyproject_text='[project]\nversion = "0.2.0"\n',
        changelog_text="# Changelog\n\n## [Unreleased]\n",
        require_changelog_section=True,
    )

    assert result.semver_ok is True
    assert result.changelog_section_exists is False
    assert result.exit_code == 1


def test_invalid_version_fails(version_module) -> None:
    result = version_module.evaluate_version(
        pyproject_text='[project]\nversion = "dev"\n',
        changelog_text="# Changelog\n",
        require_changelog_section=False,
    )

    assert result.semver_ok is False
    assert result.exit_code == 1
