from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def spec_lifecycle_module():
    path = Path("scripts/spec_lifecycle.py")
    spec = importlib.util.spec_from_file_location("spec_lifecycle", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_approved_spec_with_required_sections_is_ready(spec_lifecycle_module) -> None:
    text = """# S99 — Example

> **Status**: ✅ Approved

## 2. User Stories
- As a dev...

## 6. Edge Cases & Failure Modes
| # | Scenario | Expected Behavior |
|---|---|---|

## 7. Acceptance Criteria (Gherkin)
```gherkin
Scenario: AC-99.01 thing
  Given x
  When y
  Then z
```

## 10. Out of Scope
- Later.
"""

    result = spec_lifecycle_module.evaluate_spec(text)

    assert result.ready is True
    assert result.exit_code == 0


def test_draft_spec_is_not_ready_for_approval(spec_lifecycle_module) -> None:
    text = """# S99 — Example

> **Status**: 📝 Draft

## 7. Acceptance Criteria (Gherkin)
Scenario: AC-99.01 thing
"""

    result = spec_lifecycle_module.evaluate_spec(text)

    assert result.ready is False
    assert "status must be approved" in result.reasons
