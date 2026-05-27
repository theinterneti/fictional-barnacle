#!/usr/bin/env python3
"""Validate practical application gate evidence."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_DIR = ROOT / ".barnacle" / "evidence"
REQUIRED_FIELDS = ("gate", "command", "status", "timestamp", "summary")
FORBIDDEN_KEY_PARTS = ("api_key", "apikey", "secret", "token", "password")


@dataclass(frozen=True)
class PracticalGateResult:
    ready: bool
    files: list[str]
    reasons: list[str]

    @property
    def exit_code(self) -> int:
        return 0 if self.ready else 1


def evaluate_evidence_dir(path: Path) -> PracticalGateResult:
    files = sorted(path.glob("*.json")) if path.exists() else []
    reasons: list[str] = []
    if not files:
        reasons.append("no practical evidence JSON files found")
    for evidence_path in files:
        try:
            data = json.loads(evidence_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            reasons.append(f"{evidence_path.name} invalid JSON: {exc.msg}")
            continue
        reasons.extend(_validate_evidence(evidence_path.name, data))
    return PracticalGateResult(
        ready=not reasons,
        files=[str(path) for path in files],
        reasons=reasons,
    )


def _validate_evidence(filename: str, data: Any) -> list[str]:
    if not isinstance(data, dict):
        return [f"{filename} must be a JSON object"]
    reasons: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in data:
            reasons.append(f"{filename} missing required field: {field}")
    if data.get("status") != "pass":
        reasons.append(f"{filename} status must be pass")
    reasons.extend(_find_forbidden_keys(filename, data))
    return reasons


def _find_forbidden_keys(filename: str, data: Any, prefix: str = "") -> list[str]:
    reasons: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            dotted = f"{prefix}.{key}" if prefix else str(key)
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                reasons.append(
                    f"{filename} contains forbidden secret-like field: {dotted}"
                )
            reasons.extend(_find_forbidden_keys(filename, value, dotted))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            dotted = f"{prefix}.{index}" if prefix else str(index)
            reasons.extend(_find_forbidden_keys(filename, value, dotted))
    return reasons


def render_result(result: PracticalGateResult) -> str:
    return "\n".join(
        [
            "Practical gate",
            "==============",
            f"ready: {result.ready}",
            f"files: {len(result.files)}",
            "reasons: " + (", ".join(result.reasons) or "none"),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate practical application evidence."
    )
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = evaluate_evidence_dir(args.evidence_dir)
    if args.json:
        print(json.dumps(asdict(result) | {"exit_code": result.exit_code}, indent=2))
    else:
        print(render_result(result))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
