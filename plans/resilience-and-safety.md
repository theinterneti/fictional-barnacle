# Resilience & Safety — Component Technical Plan

> **Phase**: SDD Phase 2 — Component Plan
> **Scope**: Error handling, content moderation pipeline, rate limiting middleware
> **Input specs**: S23 (Error Handling & Resilience), S24 (Content Moderation v1), S25 (Rate Limiting & Anti-Abuse)
> **Parent plan**: `plans/system.md` (normative architecture)
> **Status**: 📝 Draft
> **Last Updated**: 2026-04-09

---

## Spec Alignment Notes

This plan implements S23, S24, and S25 subject to system.md overrides:

| Conflict | Resolution |
|----------|------------|
| S23 defines health check endpoint at `/health` | **Aligned with existing implementation.** Health checks are already at `/api/v1/health` per ops.md. S23's readiness endpoint maps to `/api/v1/health/ready`. |
| S24 requires stream interruption within 2 tokens | **v1 uses buffer-then-stream** (system.md §2.4). Content moderation inspects the complete buffer before streaming begins, so stream interruption means cancelling the buffer-to-SSE delivery — not interrupting the LLM stream. |
| S25 defines Redis-backed rate limiting | **Aligned.** Redis is already a required service. Rate limit counters use the same Redis instance with a `ratelimit:` key prefix. |

---

## 1. Error Handling Architecture (S23)

### 1.1 — Error Taxonomy

Nine error categories, each mapping to an HTTP status code and a machine-readable
`error_code` prefix:

```python
# src/tta/errors.py

from enum import StrEnum
from dataclasses import dataclass


class ErrorCategory(StrEnum):
    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    LLM_FAILURE = "llm_failure"
    SERVICE_UNAVAILABLE = "service_unavailable"
    INTERNAL = "internal"


# Category → HTTP status mapping
CATEGORY_STATUS: dict[ErrorCategory, int] = {
    ErrorCategory.VALIDATION: 422,
    ErrorCategory.AUTHENTICATION: 401,
    ErrorCategory.AUTHORIZATION: 403,
    ErrorCategory.NOT_FOUND: 404,
    ErrorCategory.CONFLICT: 409,
    ErrorCategory.RATE_LIMITED: 429,
    ErrorCategory.LLM_FAILURE: 502,
    ErrorCategory.SERVICE_UNAVAILABLE: 503,
    ErrorCategory.INTERNAL: 500,
}


@dataclass(frozen=True, slots=True)
class AppError(Exception):
    """Base application error. All domain errors inherit from this."""
    category: ErrorCategory
    code: str          # e.g. "validation.invalid_input"
    message: str       # human-readable, safe for client
    detail: str = ""   # additional context (may be redacted in production)
    retry_after_seconds: int | None = None  # for rate_limited and service_unavailable
```

### 1.2 — Error Envelope

All error responses use a consistent JSON envelope:

```python
# src/tta/api/error_handlers.py

from fastapi import Request
from fastapi.responses import JSONResponse
from tta.errors import AppError, CATEGORY_STATUS


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Convert AppError to the standard error envelope."""
    body: dict = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "correlation_id": request.state.request_id,
        }
    }
    if exc.detail:
        body["error"]["detail"] = exc.detail
    if exc.retry_after_seconds is not None:
        body["error"]["retry_after_seconds"] = exc.retry_after_seconds

    status = CATEGORY_STATUS.get(exc.category, 500)
    headers = {}
    if exc.retry_after_seconds is not None:
        headers["Retry-After"] = str(exc.retry_after_seconds)

    return JSONResponse(
        status_code=status,
        content=body,
        headers=headers,
    )
```

### 1.3 — Retry and Circuit Breaker (tenacity)

LLM calls and external service calls use tenacity for retry with circuit breaking:

```python
# src/tta/llm/resilience.py

import tenacity
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)


# Retry decorator for LLM calls
llm_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((TimeoutError, ConnectionError)),
    reraise=True,
)
```

Circuit breaker state is tracked per-service using a simple in-memory counter:

```python
# src/tta/resilience/circuit_breaker.py

import asyncio
import time
from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, reject requests
    HALF_OPEN = "half_open" # Testing recovery


class CircuitBreaker:
    """Per-service circuit breaker. Thread-safe via asyncio.Lock."""

    def __init__(
        self,
        service_name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max: int = 1,
    ):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_count = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time > self.recovery_timeout:
                return CircuitState.HALF_OPEN
        return self._state

    async def call(self, func, *args, **kwargs):
        async with self._lock:
            current = self.state
            if current == CircuitState.OPEN:
                raise AppError(
                    category=ErrorCategory.SERVICE_UNAVAILABLE,
                    code=f"service_unavailable.{self.service_name}_circuit_open",
                    message=f"Service {self.service_name} is temporarily unavailable",
                    retry_after_seconds=int(self.recovery_timeout),
                )

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise

    async def _on_success(self):
        async with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED

    async def _on_failure(self):
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
```

### 1.4 — Turn Atomicity

Turn processing follows an all-or-nothing pattern:

1. `POST /turns` creates a turn row with `status='processing'` in a transaction.
2. Pipeline stages run sequentially. On any stage failure, the turn is marked `failed`.
3. On success, the turn is marked `complete` and results are persisted atomically.
4. The SSE stream delivers either the complete narrative or an error event — never
   a partial response (v1 buffer-then-stream ensures this).

```python
# In the turn pipeline orchestrator:
async def process_turn(turn_id: str, ...) -> None:
    try:
        understood = await understand_stage(...)
        enriched = await enrich_stage(understood, ...)
        generated = await generate_stage(enriched, ...)
        # Moderation check (S24) happens here on the buffer
        moderated = await moderate_content(generated, ...)
        await persist_stage(turn_id, moderated, ...)
        await mark_turn_complete(turn_id)
        await publish_result(turn_id, moderated)
    except AppError as e:
        await mark_turn_failed(turn_id, error=e)
        await publish_error(turn_id, error=e)
    except Exception as e:
        await mark_turn_failed(turn_id, error=wrap_internal(e))
        await publish_error(turn_id, error=wrap_internal(e))
```

### 1.5 — SSE Error Events

Error events in the SSE stream use the same error envelope:

```
event: error
data: {"code": "llm_failure.timeout", "message": "Narrative generation timed out", "correlation_id": "abc-123"}
```

After an error event, the stream sends `stream_end` and closes.

### 1.6 — Health Endpoint Enhancement

The existing `/api/v1/health` is extended with subsystem checks:

```python
# Subsystem health checks
async def check_postgres(pool) -> SubsystemStatus: ...
async def check_redis(redis) -> SubsystemStatus: ...
async def check_neo4j(driver) -> SubsystemStatus: ...
async def check_llm(client) -> SubsystemStatus: ...

# Aggregate: healthy (all up), degraded (some down), unhealthy (critical down)
```

Readiness endpoint (`/api/v1/health/ready`) returns 200 only when all critical
subsystems (Postgres, Redis) are available. Used by load balancer health checks.

---

## 2. Content Moderation Pipeline (S24)

### 2.1 — Architecture

Content moderation is a post-generation stage that inspects the full LLM response
buffer before streaming to the player. This aligns with the buffer-then-stream
architecture (system.md §2.4).

```
LLM Generate → Buffer → Moderate → Stream to Player
                           │
                           ├─ PASS → stream normally
                           ├─ BLOCK → replace with safe response
                           └─ FLAG → stream + log for review
```

### 2.2 — Content Classifier

```python
# src/tta/moderation/classifier.py

from enum import StrEnum


class ContentCategory(StrEnum):
    REAL_WORLD_VIOLENCE = "real_world_violence"
    SELF_HARM = "self_harm"
    CSAM = "csam"
    HATE_SPEECH = "hate_speech"
    REAL_PERSON_HARM = "real_person_harm"
    ILLEGAL_INSTRUCTION = "illegal_instruction"
    SEXUAL_EXPLICIT = "sexual_explicit"
    SUBSTANCE_GLORIFICATION = "substance_glorification"
    PERSONAL_DATA_LEAK = "personal_data_leak"
    HALLUCINATED_REAL_ENTITY = "hallucinated_real_entity"


class ModerationAction(StrEnum):
    PASS = "pass"
    FLAG = "flag"
    BLOCK = "block"


# Non-overridable categories (always block)
ALWAYS_BLOCK = frozenset({
    ContentCategory.CSAM,
    ContentCategory.SELF_HARM,
    ContentCategory.REAL_WORLD_VIOLENCE,
    ContentCategory.HATE_SPEECH,
    ContentCategory.REAL_PERSON_HARM,
    ContentCategory.ILLEGAL_INSTRUCTION,
})


@dataclass
class ModerationResult:
    action: ModerationAction
    categories_detected: list[ContentCategory]
    confidence: float  # 0.0 - 1.0
    content_hash: str  # SHA-256 of inspected content
    replacement_text: str | None = None
```

### 2.3 — Moderation Strategies

v1 implements two moderation backends, selected by configuration:

1. **LLM-based moderation** (default): A separate LLM call with a moderation-specific
   prompt that classifies content. Uses a smaller, faster model (e.g., GPT-4o-mini).
2. **Keyword/regex fallback**: Pattern-based detection for obvious violations. Used as
   a fast pre-filter and as fallback when the LLM moderation call fails.

```python
# src/tta/moderation/service.py

class ModerationService:
    """Orchestrates content moderation with fallback."""

    def __init__(self, llm_client, config: ModerationConfig):
        self.llm_moderator = LLMModerator(llm_client, config)
        self.keyword_moderator = KeywordModerator(config)
        self.config = config

    async def moderate(self, content: str, context: TurnContext) -> ModerationResult:
        # Fast keyword pre-filter
        keyword_result = self.keyword_moderator.check(content)
        if keyword_result.action == ModerationAction.BLOCK:
            return keyword_result

        # LLM-based moderation
        try:
            return await self.llm_moderator.check(content, context)
        except Exception:
            # Fail-open by default (configurable)
            if self.config.fail_open:
                return ModerationResult(
                    action=ModerationAction.FLAG,
                    categories_detected=[],
                    confidence=0.0,
                    content_hash=hash_content(content),
                )
            else:
                return ModerationResult(
                    action=ModerationAction.BLOCK,
                    categories_detected=[],
                    confidence=0.0,
                    content_hash=hash_content(content),
                    replacement_text=SAFE_FALLBACK_TEXT,
                )
```

### 2.4 — Block Response

When content is blocked, the player receives a safe replacement narrative:

```python
SAFE_FALLBACK_TEXT = (
    "The story pauses for a moment as the narrator reconsiders the "
    "direction of the tale. Let's explore a different path..."
)
```

The replacement is delivered via the normal SSE stream. The player sees a narrative
continuation, not a raw error message. An `error` SSE event is NOT sent for blocks —
blocks are transparent to the player as narrative redirections.

### 2.5 — Audit Trail

Every moderation decision is logged:

```python
# Moderation audit record (stored in Postgres)
class ModerationAuditRecord:
    id: str
    turn_id: str
    player_id: str
    action: ModerationAction
    categories_detected: list[str]
    confidence: float
    content_hash: str       # SHA-256, not the content itself
    timestamp: datetime
    model_used: str | None  # moderation model
```

Content itself is NOT stored in the audit trail. Only the SHA-256 hash is stored for
correlation. This protects privacy while enabling pattern detection.

### 2.6 — Configuration

```python
# In Settings (config.py additions)
class ModerationConfig:
    enabled: bool = True
    fail_open: bool = True              # fail-open by default
    moderation_model: str = "gpt-4o-mini"
    confidence_threshold: float = 0.7   # below this → FLAG, above → action
    max_flags_per_session: int = 3      # escalate to block after 3 flags
    keyword_patterns_path: str = "config/moderation_keywords.yml"
```

---

## 3. Rate Limiting Middleware (S25)

### 3.1 — Architecture

Rate limiting is implemented as FastAPI middleware using Redis-backed sliding window
counters. Two tiers: per-player (authenticated) and per-IP (unauthenticated).

```
Request → Rate Limit Middleware → Route Handler
              │
              ├─ Check Redis counter
              ├─ Under limit → increment + proceed
              └─ Over limit → 429 with Retry-After
```

### 3.2 — Sliding Window Implementation

```python
# src/tta/middleware/rate_limit.py

import time
import redis.asyncio as redis


class SlidingWindowRateLimiter:
    """Redis-backed sliding window rate limiter."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def check_and_increment(
        self, key: str, limit: int, window_seconds: int
    ) -> tuple[bool, int, int]:
        """
        Returns (allowed, remaining, retry_after_seconds).
        Uses Redis sorted set with timestamp scores.
        """
        now = time.time()
        window_start = now - window_seconds
        pipe = self.redis.pipeline(transaction=True)

        # Remove expired entries
        pipe.zremrangebyscore(key, 0, window_start)
        # Count current entries
        pipe.zcard(key)
        # Add current request
        pipe.zadd(key, {f"{now}": now})
        # Set TTL on the key
        pipe.expire(key, window_seconds)

        results = await pipe.execute()
        current_count = results[1]

        if current_count >= limit:
            # Over limit — calculate retry_after
            oldest = await self.redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                retry_after = int(oldest[0][1] + window_seconds - now) + 1
            else:
                retry_after = window_seconds
            return False, 0, retry_after

        remaining = limit - current_count - 1
        return True, remaining, 0
```

### 3.3 — Endpoint Group Defaults

```python
# Rate limit configuration per endpoint group
RATE_LIMITS: dict[str, RateLimitConfig] = {
    "turn_submission": RateLimitConfig(
        per_player_limit=10,
        per_player_window=60,      # 10 turns per minute
        per_ip_limit=30,
        per_ip_window=60,
    ),
    "game_creation": RateLimitConfig(
        per_player_limit=5,
        per_player_window=300,     # 5 games per 5 minutes
        per_ip_limit=10,
        per_ip_window=300,
    ),
    "auth": RateLimitConfig(
        per_player_limit=None,     # N/A for unauthenticated
        per_ip_limit=20,
        per_ip_window=900,         # 20 attempts per 15 minutes
    ),
    "general_read": RateLimitConfig(
        per_player_limit=60,
        per_player_window=60,      # 60 reads per minute
        per_ip_limit=120,
        per_ip_window=60,
    ),
}
```

### 3.4 — Response Headers

Rate-limited responses include standard headers:

```python
headers = {
    "X-RateLimit-Limit": str(limit),
    "X-RateLimit-Remaining": str(remaining),
    "X-RateLimit-Reset": str(reset_timestamp),
    "Retry-After": str(retry_after_seconds),  # only on 429
}
```

### 3.5 — Anti-Abuse Detection

Beyond rate limiting, the middleware detects abuse patterns:

1. **Rapid-fire turns**: >5 turn submissions in 10 seconds → escalating cooldown
2. **Credential stuffing**: >10 failed logins in 5 minutes from one IP → IP block (15 min)
3. **Connection flood**: >50 SSE connections from one IP in 1 minute → IP block (5 min)

Escalating cooldowns: 1min → 5min → 15min → 1hour → 24hours (max).

### 3.6 — In-Memory Fallback

When Redis is unavailable, rate limiting falls back to an in-memory sliding window
per-process. This is less accurate (not shared across instances) but prevents bypassing
rate limits entirely:

```python
class InMemoryRateLimiter:
    """Fallback when Redis is unavailable. Per-process only."""

    def __init__(self):
        self._windows: dict[str, list[float]] = {}
```

---

## 4. Configuration Summary

New settings added to `src/tta/config.py`:

```python
class Settings(BaseSettings):
    # ... existing settings ...

    # Error handling (S23)
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: int = 30
    health_check_timeout: int = 5

    # Content moderation (S24)
    moderation_enabled: bool = True
    moderation_fail_open: bool = True
    moderation_model: str = "gpt-4o-mini"
    moderation_confidence_threshold: float = 0.7
    moderation_max_flags_per_session: int = 3

    # Rate limiting (S25)
    rate_limit_enabled: bool = True
    rate_limit_turn_per_minute: int = 10
    rate_limit_game_create_per_5min: int = 5
    rate_limit_auth_per_15min: int = 20
    rate_limit_read_per_minute: int = 60
```

---

## 5. Database Migrations

### 5.1 — Moderation Audit Table

```sql
-- Alembic migration: add moderation_audit table
CREATE TABLE moderation_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id UUID NOT NULL REFERENCES turns(id),
    player_id UUID NOT NULL,
    action VARCHAR(10) NOT NULL,  -- pass, flag, block
    categories_detected JSONB NOT NULL DEFAULT '[]',
    confidence FLOAT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,  -- SHA-256
    model_used VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_moderation_audit_turn ON moderation_audit(turn_id);
CREATE INDEX idx_moderation_audit_player ON moderation_audit(player_id);
CREATE INDEX idx_moderation_audit_action ON moderation_audit(action)
    WHERE action IN ('flag', 'block');
```

---

## 6. File Inventory

Files this plan introduces:

| File | Purpose | New/Modified |
|---|---|---|
| `src/tta/errors.py` | Error taxonomy, AppError, error categories | New |
| `src/tta/api/error_handlers.py` | FastAPI exception handlers, error envelope | Modified |
| `src/tta/resilience/circuit_breaker.py` | Per-service circuit breaker | New |
| `src/tta/moderation/__init__.py` | Moderation package | New |
| `src/tta/moderation/classifier.py` | Content categories, classification | New |
| `src/tta/moderation/service.py` | Moderation orchestration | New |
| `src/tta/moderation/keyword.py` | Keyword/regex fallback moderator | New |
| `src/tta/moderation/llm_moderator.py` | LLM-based content moderation | New |
| `src/tta/moderation/audit.py` | Moderation audit trail | New |
| `src/tta/middleware/rate_limit.py` | Rate limiting middleware | New |
| `src/tta/middleware/anti_abuse.py` | Anti-abuse pattern detection | New |
| `config/moderation_keywords.yml` | Keyword patterns for content moderation | New |
| `src/tta/config.py` | New settings for moderation, rate limiting | Modified |
| `tests/unit/moderation/` | Moderation unit tests | New |
| `tests/unit/middleware/` | Rate limiting unit tests | New |
| `tests/unit/resilience/` | Circuit breaker unit tests | New |
| `tests/bdd/features/content_moderation.feature` | BDD scenarios for S24 ACs | New |
| `tests/bdd/features/rate_limiting.feature` | BDD scenarios for S25 ACs | New |

---

## 7. Implementation Waves

This plan spans multiple implementation waves:

| Wave | Focus | Specs | Estimated Scope |
|------|-------|-------|-----------------|
| Wave 9 | Error handling foundation | S23 (core errors, health) | Error taxonomy, handlers, health enhancement |
| Wave 10 | Content moderation | S24 | Moderation pipeline, audit, keyword fallback |
| Wave 11 | Rate limiting | S25 | Middleware, Redis counters, anti-abuse |

Each wave produces a PR-ready increment that can be independently tested and deployed.
