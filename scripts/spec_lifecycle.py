#!/usr/bin/env python3
"""Spec lifecycle readiness checks."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpecLifecycleResult:
    ready: bool
    reasons: list[str]

    @property
    def exit_code(self) -> int:
        return 0 if self.ready else 1


def evaluate_spec(text: str) -> SpecLifecycleResult:
    reasons: list[str] = []
    if "✅ Approved" not in text and "Status**: Approved" not in text:
        reasons.append("status must be approved")
    required_markers = {
        "user stories section": "User Stories",
        "edge cases section": "Edge Cases",
        "acceptance criteria section": "Acceptance Criteria",
        "out of scope section": "Out of Scope",
        "gherkin scenarios": "Given",
    }
    for reason, marker in required_markers.items():
        if marker not in text:
            reasons.append(f"missing {reason}")
    return SpecLifecycleResult(ready=not reasons, reasons=reasons)


def render_result(result: SpecLifecycleResult) -> str:
    lines = ["Spec lifecycle check", "===================="]
    lines.append(f"ready: {result.ready}")
    lines.append("reasons: " + (", ".join(result.reasons) or "none"))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a spec is ready for approved work."
    )
    parser.add_argument("spec", help="Spec markdown path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    text = Path(args.spec).read_text(encoding="utf-8")
    result = evaluate_spec(text)
    if args.json:
        print(json.dumps(asdict(result) | {"exit_code": result.exit_code}, indent=2))
    else:
        print(render_result(result))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
