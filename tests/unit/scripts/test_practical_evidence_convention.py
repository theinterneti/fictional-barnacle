from __future__ import annotations

from pathlib import Path


def test_practical_evidence_readme_documents_no_spend_convention() -> None:
    readme = Path(".barnacle/evidence/README.md").read_text()

    assert "No-spend practical gates" in readme
    assert "Spy/Noop" in readme
    assert "status" in readme
    assert "command" in readme


def test_practical_gate_sample_is_present() -> None:
    sample = Path(".barnacle/evidence/local-automation-phase6.json").read_text()

    assert '"status": "pass"' in sample
    assert '"gate": "local-automation-phase6"' in sample
