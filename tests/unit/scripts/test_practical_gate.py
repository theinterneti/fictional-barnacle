from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def practical_module():
    path = Path("scripts/practical_gate.py")
    spec = importlib.util.spec_from_file_location("practical_gate", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_valid_practical_evidence_passes(practical_module, tmp_path: Path) -> None:
    evidence = tmp_path / "phase6.json"
    evidence.write_text(
        json.dumps(
            {
                "gate": "phase6-smoke",
                "command": "make gate",
                "status": "pass",
                "timestamp": "2026-05-27T00:00:00Z",
                "summary": "Full local gate passed.",
            }
        )
    )

    result = practical_module.evaluate_evidence_dir(tmp_path)

    assert result.ready is True
    assert result.exit_code == 0
    assert result.files == [str(evidence)]


def test_missing_evidence_fails(practical_module, tmp_path: Path) -> None:
    result = practical_module.evaluate_evidence_dir(tmp_path)

    assert result.ready is False
    assert "no practical evidence JSON files found" in result.reasons


def test_failed_evidence_fails(practical_module, tmp_path: Path) -> None:
    evidence = tmp_path / "failed.json"
    evidence.write_text(
        json.dumps(
            {
                "gate": "phase6-smoke",
                "command": "make gate",
                "status": "fail",
                "timestamp": "2026-05-27T00:00:00Z",
                "summary": "Gate failed.",
            }
        )
    )

    result = practical_module.evaluate_evidence_dir(tmp_path)

    assert result.ready is False
    assert "failed.json status must be pass" in result.reasons


def test_malformed_evidence_reports_missing_fields(
    practical_module, tmp_path: Path
) -> None:
    evidence = tmp_path / "bad.json"
    evidence.write_text(json.dumps({"gate": "phase6-smoke", "status": "pass"}))

    result = practical_module.evaluate_evidence_dir(tmp_path)

    assert result.ready is False
    assert "bad.json missing required field: command" in result.reasons


def test_evidence_rejects_secret_like_fields(practical_module, tmp_path: Path) -> None:
    evidence = tmp_path / "secret.json"
    evidence.write_text(
        json.dumps(
            {
                "gate": "phase6-smoke",
                "command": "make gate",
                "status": "pass",
                "timestamp": "2026-05-27T00:00:00Z",
                "summary": "Full local gate passed.",
                "metadata": {"api_key": "sk_liv...owed"},
            }
        )
    )

    result = practical_module.evaluate_evidence_dir(tmp_path)

    assert result.ready is False
    assert (
        "secret.json contains forbidden secret-like field: metadata.api_key"
        in result.reasons
    )
