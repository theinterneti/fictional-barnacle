from __future__ import annotations

from pathlib import Path


def test_release_workflow_runs_release_check_before_publish() -> None:
    workflow = Path(".github/workflows/release.yml").read_text()

    assert "workflow_dispatch:" in workflow
    assert "make release-check" in workflow
    assert "gh --version" in workflow
    assert "gh release create" in workflow
    assert "permissions:" in workflow
    assert "contents: write" in workflow


def test_release_workflow_uses_manual_tag_input() -> None:
    workflow = Path(".github/workflows/release.yml").read_text()

    assert "tag:" in workflow
    assert "required: true" in workflow
    assert "${{ inputs.tag }}" in workflow
