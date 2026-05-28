# S71 Langfuse Integration — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Extend S15 observability with user/session lifecycle tracing, prompt provenance, and eval score integration in self-hosted Langfuse.

**Architecture:** A fire-and-forget `LangfuseManager` wraps the Langfuse SDK. Lifecycle tracing hooks into existing FastAPI auth/session routes without new endpoints. Prompt provenance enriches existing S15 LLM call instrumentation. Evaluation scores flow from S45 pipeline. All Langfuse calls are non-blocking — unavailability never affects gameplay.

**Tech Stack:** Langfuse Python SDK, FastAPI dependency injection, existing S11 player identity, S15 observability base, S45 evaluation pipeline, SHA-256 pseudonymization.

---

## Bundle Scope

Single spec: S71. This plan does not cover S15's existing LLM call instrumentation (FR-15.17–15.21) — it adds the three tracing surfaces S15 left unaddressed.

---

## Current-State Anchors

- `src/tta/observability/__init__.py` — existing Langfuse init and LLM tracing
- `src/tta/config.py` — Pydantic Settings with existing Langfuse env vars
- `src/tta/api/auth.py` — registration, login, logout endpoints
- `src/tta/api/sessions.py` — session create, resume, end
- `src/tta/prompts/` — S09 prompt management
- `src/tta/evals/pipeline.py` — S45 evaluation pipeline

---

## Build Order

### Task 1: LangfuseManager singleton

**Objective:** Centralized fire-and-forget trace/score emission with degraded-mode resilience.

**Files:**
- Create: `src/tta/observability/langfuse_manager.py`
- Modify: `src/tta/config.py` (add `TTA_LANGFUSE_ENABLED`, `TTA_LANGFUSE_SAMPLE_RATE`, `TTA_LANGFUSE_ENVIRONMENT`)
- Create: `tests/unit/observability/test_langfuse_manager.py`

**Step 1: Write failing test**

```python
# tests/unit/observability/test_langfuse_manager.py
import pytest
from unittest.mock import patch, MagicMock
from tta.observability.langfuse_manager import LangfuseManager

def test_disabled_manager_skips_trace():
    manager = LangfuseManager(enabled=False, host="http://localhost:3000", public_key="pk", secret_key="sk")
    with patch("langfuse.Langfuse") as mock_lf:
        manager.trace("test.event", {"key": "value"}, session_id="s1")
        mock_lf.assert_not_called()

def test_manager_swallows_langfuse_errors():
    manager = LangfuseManager(enabled=True, host="http://localhost:3000", public_key="pk", secret_key="sk", environment="test")
    with patch.object(manager, "_client") as mock_client:
        mock_client.trace.side_effect = Exception("connection refused")
        # Should not raise
        manager.trace("test.event", {"key": "value"})
```

**Step 2: Run to verify failure**
```bash
uv run pytest tests/unit/observability/test_langfuse_manager.py -v
# Expected: FAIL — module not found
```

**Step 3: Implement**
```python
# src/tta/observability/langfuse_manager.py
from __future__ import annotations
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

@dataclass
class LangfuseManager:
    enabled: bool = False
    host: str = ""
    public_key: str = ""
    secret_key: str = ""
    environment: str = "development"
    sample_rate: float = 1.0
    _client: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.enabled:
            try:
                import langfuse
                self._client = langfuse.Langfuse(
                    host=self.host,
                    public_key=self.public_key,
                    secret_key=self.secret_key,
                    environment=self.environment,
                )
            except Exception:
                logger.warning("langfuse init failed", exc_info=True)
                self.enabled = False

    def trace(self, name: str, metadata: dict[str, Any], *, session_id: str = "", user_id: str = "") -> None:
        if not self.enabled or not self._client:
            return
        try:
            trace = self._client.trace(name=name, session_id=session_id, user_id=user_id, metadata=metadata)
        except Exception:
            logger.debug("langfuse trace dropped", extra={"event": name}, exc_info=True)
```

**Step 4: Run tests**
```bash
uv run pytest tests/unit/observability/test_langfuse_manager.py -v
# Expected: PASS
```

**Step 5: Commit**
```bash
git add src/tta/observability/langfuse_manager.py tests/unit/observability/test_langfuse_manager.py
git commit -m "feat(s71): add LangfuseManager with degraded-mode resilience"
```

---

### Task 2: User lifecycle instrumentation

**Objective:** Trace account registration, login, logout, and admin actions.

**Files:**
- Modify: `src/tta/api/auth.py`
- Modify: `src/tta/api/admin.py`
- Create: `tests/unit/api/test_user_lifecycle_traces.py`

**Step 1: Pseudonymization utility**
```python
# Add to src/tta/observability/langfuse_manager.py
def pseudonymize(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]
```

**Step 2: Instrument auth endpoints**
Inject `LangfuseManager` via FastAPI dependency and emit traces:
- `POST /register` → `user.register` trace (pseudonymized user_id)
- `POST /login` → `user.login` trace
- `POST /logout` → `user.logout` trace

**Step 3: TDD cycle** — write test, fail, implement, pass, commit.

---

### Task 3: Session lifecycle instrumentation

**Objective:** Map S11 sessions to Langfuse sessions, trace create/resume/end/timeout.

**Files:**
- Modify: `src/tta/api/sessions.py`

Emits: `session.create`, `session.resume`, `session.end`, `session.timeout` traces with `session_id` grouping.

---

### Task 4: Prompt provenance enrichment

**Objective:** Attach prompt version metadata to S15's existing LLM generation traces.

**Files:**
- Modify: `src/tta/prompts/bridge.py` (or equivalent S09 integration point)
- Modify: `src/tta/observability/__init__.py` (enrich generation metadata)

Each LLM generation SHALL include `prompt_name`, `prompt_version`, `prompt_source` fields. When Langfuse is the prompt source, include the `langfuse_prompt` object for SDK-native linking.

---

### Task 5: Evaluation score emission

**Objective:** Push S45 evaluation scores into Langfuse traces.

**Files:**
- Modify: `src/tta/evals/pipeline.py`
- Modify: `src/tta/observability/langfuse_manager.py` (add `emit_score` method)

Score naming: `eval.{dimension}` (e.g., `eval.coherence`, `eval.engagement`). Scores link to the session's Langfuse trace by `trace_id`.

---

### Task 6: Integration gate

**Objective:** Prove the full tracing surface works end-to-end.

**Scenario:**
1. Register a test player → verify `user.register` trace
2. Create a game session → verify `session.create` trace
3. Submit a turn → verify LLM generation carries prompt provenance
4. Run evaluation → verify scores appear
5. End session → verify `session.end` trace
6. Disconnect Langfuse → verify gameplay continues normally

---

## Testing Strategy

- Unit tests for `LangfuseManager` resilience (disabled, error, sampling)
- Integration tests for lifecycle trace emission (mock Langfuse client)
- Privacy audit: verify no raw PII in trace metadata
- Resilience test: app runs normally with Langfuse unreachable

## Risk Controls

- **Non-blocking:** All Langfuse calls are fire-and-forget with try-except
- **Privacy:** Player IDs pseudonymized via SHA-256 before leaving app boundary
- **Degraded mode:** `TTA_LANGFUSE_ENABLED=false` skips all Langfuse work
- **No new endpoints:** Tracing hooks into existing routes, no new API surface
