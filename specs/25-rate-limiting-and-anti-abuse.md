# S25 — Rate Limiting & Anti-Abuse

> **Status**: ✅ Approved
> **Release Baseline**: 🔒 v1 Closed
> **Implementation Fit**: ⚠️ Partial
> **Level**: 3 — Platform
> **Dependencies**: S10 (API & Streaming), S11 (Player Identity & Sessions), S23 (Error Handling), S24 (Content Moderation)
> **Last Updated**: 2026-04-09

---

## How to Read This Spec

This is a **functional specification** — it describes *what* the system does, not *how*
it's built. It is one half of a testable contract:

- **This spec** (the "what") defines behavior, acceptance criteria, and boundaries
- **The technical plan** (the "how") will define architecture, stack, and implementation
- **Tasks** will decompose both into small, reviewable chunks of work

Acceptance criteria use **Gherkin syntax** (Given/When/Then) so they can be directly
executed as automated BDD tests using frameworks like Behave or pytest-bdd.

---

## 1. Purpose

This spec defines rate limiting and anti-abuse mechanisms for TTA's API. Every public
endpoint must be protected against excessive use — whether accidental (tight polling
loops) or malicious (denial-of-service, resource exhaustion, credential stuffing).

Rate limiting serves three goals:
1. **Stability** — Prevent any single player or client from degrading service for others
2. **Cost control** — LLM calls are expensive; unbounded usage is unsustainable
3. **Abuse prevention** — Detect and throttle automated/malicious access patterns

### Design values applied

| Value | Implication |
|---|---|
| **Fun** | Rate limits must be generous enough that normal gameplay never hits them. A player in deep flow should never see "too many requests." |
| **Transparency** | Rate limit headers are always present so clients can self-regulate. Error responses explain what happened and when to retry. |
| **Fairness** | Limits are per-player, not global. One player's heavy use doesn't degrade another's experience. |
| **Craftsmanship** | Rate limiting is implemented consistently across all endpoints via middleware, not ad-hoc per-route. |

---

## 2. User Stories

### US-25.1 — Player experiences smooth gameplay under normal use
> As a **player**, I want to play the game at a natural pace without encountering rate
> limit errors, so that the experience feels seamless and responsive.

### US-25.2 — Player receives clear feedback when rate limited
> As a **player**, if I somehow trigger a rate limit (e.g., rapid resubmission), I want
> a clear indication of when I can try again, so that I'm not left guessing.

### US-25.3 — Operator controls rate limit configuration
> As an **operator**, I want to configure rate limits per endpoint and per player tier, so
> that I can balance cost, performance, and user experience.

### US-25.4 — System is protected from automated abuse
> As an **operator**, I want the system to detect and throttle automated access patterns
> (bots, credential stuffing, scraping), so that the platform remains available for
> legitimate players.

### US-25.5 — Developer understands rate limit behavior
> As a **developer**, I want rate limiting to be applied consistently via middleware with
> predictable behavior, so that I don't need to implement per-endpoint protection.

---

## 3. Functional Requirements

### 3.1 — Rate Limit Tiers

**FR-25.01**: The system SHALL enforce rate limits at two tiers:

| Tier | Scope | Purpose |
|---|---|---|
| **Per-player** | Identified by player session token | Prevents individual abuse |
| **Per-IP** | Identified by source IP address | Prevents unauthenticated abuse, credential stuffing |

**FR-25.02**: Per-player limits take precedence when a player is authenticated. Per-IP
limits apply to unauthenticated requests (registration, login).

### 3.2 — Endpoint Rate Limits

**FR-25.03**: Rate limits SHALL be configurable per endpoint group:

| Endpoint Group | Default Per-Player Limit | Default Per-IP Limit | Window |
|---|---|---|---|
| Turn submission (`POST /turns`) | 10 requests/minute | 20 requests/minute | Sliding window |
| Game management (create, list, delete) | 30 requests/minute | 60 requests/minute | Sliding window |
| Authentication (register, login) | N/A | 10 requests/minute | Sliding window |
| SSE streaming (`GET /games/{id}/stream`) | 5 connections/minute | 10 connections/minute | Sliding window |
| Health/status endpoints | No limit | No limit | — |

**FR-25.04**: Turn submission (`POST /turns`) SHALL have a separate concurrent-request
limit: only 1 turn per game may be in-flight at a time. A second submission for the
same game while one is processing SHALL receive a 409 Conflict (per S23 error taxonomy).

**FR-25.05**: Rate limit defaults SHALL be configurable via environment variables
without requiring code changes. Configuration format: `TTA_RATE_LIMIT_{GROUP}_{TIER}`.

### 3.3 — Rate Limit Algorithm

**FR-25.06**: The system SHALL use the **sliding window** algorithm for rate limiting.
This provides smoother limit enforcement than fixed-window algorithms, avoiding burst
allowances at window boundaries.

**FR-25.07**: Rate limit state SHALL be stored in Redis (per S12's session cache). If
Redis is unavailable, the system SHALL fall back to in-memory rate limiting with a
logged warning and degraded accuracy (per S23 degradation behavior).

### 3.4 — Response Headers

**FR-25.08**: ALL API responses (including successful ones) SHALL include rate limit
headers:
- `X-RateLimit-Limit`: Maximum requests allowed in the current window
- `X-RateLimit-Remaining`: Requests remaining in the current window
- `X-RateLimit-Reset`: Unix timestamp when the window resets

**FR-25.09**: When a request is rate limited, the response SHALL:
- Return HTTP 429 (Too Many Requests)
- Include a `Retry-After` header with the number of seconds to wait
- Include the S23 error envelope with code `rate_limited` and `retry_after_seconds`
- NOT count the rejected request against the rate limit

### 3.5 — Anti-Abuse Detection

**FR-25.10**: The system SHALL detect and respond to the following abuse patterns:

| Pattern | Detection | Response |
|---|---|---|
| **Rapid-fire requests** | >3x the rate limit within one window | Increase cooldown period to 2x the normal window |
| **Credential stuffing** | >5 failed auth attempts from one IP in 5 minutes | Block IP for 15 minutes. Log at WARN. |
| **Concurrent connection flood** | >20 SSE connections from one IP | Reject new connections. Log at WARN. |
| **Abnormal payload** | Requests with suspiciously large or malformed bodies | Return 400 (per S23). Log at WARN. |

**FR-25.11**: Anti-abuse responses SHALL be escalating: the first violation triggers a
warning and temporary cooldown; repeated violations within a configurable window
(default: 1 hour) extend the cooldown exponentially up to a configurable maximum
(default: 24 hours).

**FR-25.12**: All anti-abuse actions SHALL be logged as structured events (per S15/S23)
with event type `abuse_detected`, including the pattern type, source, and action taken.

### 3.6 — Player Communication

**FR-25.13**: Rate limit error messages SHALL be player-friendly:
- For turn submission: "You're moving faster than the story can keep up. Take a breath
  and try again in a moment."
- For general API: "Too many requests. Please wait {retry_after} seconds."
- Messages SHALL NOT reveal internal rate limit configuration or thresholds.

**FR-25.14**: Rate limit enforcement SHALL NOT interrupt active SSE streams. If a player
is currently receiving a narrative stream, that stream continues to completion even if
the player is subsequently rate limited.

### 3.7 — Operator Controls

**FR-25.15**: Operators SHALL be able to (via S26 admin API):
- View current rate limit counters for a specific player or IP
- Temporarily increase or decrease limits for a specific player
- Whitelist specific IPs from rate limiting (for testing, internal tools)
- View a log of all anti-abuse actions

**FR-25.16**: Rate limit configuration changes SHALL take effect within 60 seconds
without requiring a restart.

---

## 4. Non-Functional Requirements

### NFR-25.1 — Rate Limit Overhead
**Category**: Performance
**Target**: Rate limit evaluation SHALL add less than 5ms (p95) to request processing
time. Redis round-trip for rate limit checks SHALL be sub-millisecond on a co-located
deployment.

### NFR-25.2 — Normal Gameplay Headroom
**Category**: Usability
**Target**: Default rate limits SHALL allow a player to submit turns at a sustained pace
of one turn every 6 seconds (10/min) without hitting limits. This is 2-3x faster than
the expected natural pace of ~1 turn per 15-30 seconds.

### NFR-25.3 — Scalability
**Category**: Performance
**Target**: Rate limiting SHALL function correctly across multiple application instances
sharing the same Redis backend. Per-player limits SHALL be globally consistent (not
per-instance).

### NFR-25.4 — Observability
**Category**: Operations
**Target**: Rate limit events (enforcement, abuse detection) SHALL be emitted as
structured metrics: `tta_rate_limit_enforced_total` (counter, labels: endpoint_group,
tier) and `tta_abuse_detected_total` (counter, labels: pattern_type).

---

## 5. User Journeys

### Journey 1: Normal gameplay — rate limits invisible

- **Trigger**: Player plays at a natural pace (~1 turn per 20 seconds).
- **Steps**:
  1. Player submits a turn. Request includes rate limit headers showing 9/10 remaining.
  2. Player reads narrative for 20 seconds. Submits another turn.
  3. Window has reset. Headers show 10/10 remaining.
- **Outcome**: Player never approaches limits. Headers are available for well-behaved clients.

### Journey 2: Player rapid-submits during excitement

- **Trigger**: Player excitedly submits 10 turns in 60 seconds.
- **Steps**:
  1. Turns 1-10 are processed normally. Headers show 0/10 remaining.
  2. Player submits turn 11. Receives 429 with retry_after=12 seconds.
  3. Player waits 12 seconds. Submits again. Processed normally.
- **Outcome**: Brief pause. No lasting consequence. Player continues playing.

### Journey 3: Bot attempts to scrape game content

- **Trigger**: Automated script submits 50 requests in 10 seconds.
- **Steps**:
  1. First 10 requests processed (within limit).
  2. Requests 11-50 receive 429 responses.
  3. Anti-abuse detects rapid-fire pattern (>3x limit). Escalates cooldown to 2 minutes.
  4. Bot continues. Cooldown escalates to 4 minutes, then 8 minutes.
  5. Operator sees `abuse_detected` events in logs.
- **Outcome**: Bot is effectively throttled. Legitimate players unaffected.

### Journey 4: Redis is down

- **Trigger**: Redis connection lost.
- **Steps**:
  1. Rate limit middleware detects Redis unavailability.
  2. Falls back to in-memory rate limiting (per-instance, not globally consistent).
  3. Logs warning: "Rate limiting degraded: using in-memory fallback."
  4. `/api/v1/health` reports Redis as degraded (per S23).
  5. When Redis recovers, rate limiting returns to normal.
- **Outcome**: Rate limiting continues with reduced accuracy. System stays available.

---

## 6. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| EC-25.1 | Player is behind a shared IP (NAT, VPN, university network) | Per-player limits (session-based) apply to authenticated requests. Per-IP limits only affect unauthenticated endpoints. Shared IPs do not cause cross-player rate limiting for authenticated gameplay. |
| EC-25.2 | Player opens multiple browser tabs with the same session | All tabs share the same per-player rate limit. SSE connection limit (5/min) may be hit. Oldest connections are not forcibly closed — new ones are rejected. |
| EC-25.3 | Clock skew between application instances | Sliding window uses Redis server time (not application time) for consistency. |
| EC-25.4 | Player's session expires while rate-limited | Rate limit is still enforced for the IP. Player can re-authenticate and get fresh per-player limits (since the rate limit counter was on the old session). |
| EC-25.5 | Turn processing takes longer than the rate limit window | The in-flight turn continues processing. The rate limit window resets. Player can submit again immediately after the window resets. The concurrent-request limit (FR-25.04) still prevents parallel turns for the same game. |
| EC-25.6 | DDoS attack from many distributed IPs | Per-IP limits provide some protection. S25 does NOT define full DDoS mitigation — that requires infrastructure-level protection (CDN, WAF). Noted in Out of Scope. |
| EC-25.7 | Operator whitelists an IP that is later used for abuse | Whitelisted IPs bypass rate limiting. Operator must manage whitelists carefully. Anti-abuse logging still fires for whitelisted IPs. |
| EC-25.8 | Rate limit Redis keys accumulate (memory leak) | All rate limit keys have TTL equal to the window duration. Redis handles eviction automatically. |

---

## 7. Acceptance Criteria (Gherkin)

```gherkin
Feature: Rate Limiting & Anti-Abuse

  Scenario: AC-25.1 — Normal gameplay within limits
    Given a player with a valid session
    And the turn submission rate limit is 10 per minute
    When the player submits 9 turns in 60 seconds
    Then all turns are processed successfully
    And each response includes X-RateLimit-Remaining headers

  Scenario: AC-25.2 — Rate limit enforced
    Given a player has exhausted their turn submission rate limit
    When the player submits another turn
    Then the response status is 429
    And the response includes a Retry-After header
    And the error body contains code "rate_limited" and retry_after_seconds
    And the rejected request does not count against the limit

  Scenario: AC-25.3 — Rate limit headers on all responses
    Given a player submits any API request
    When the response is returned
    Then the response includes X-RateLimit-Limit header
    And the response includes X-RateLimit-Remaining header
    And the response includes X-RateLimit-Reset header

  Scenario: AC-25.4 — Concurrent turn prevention
    Given a player has a turn currently in-flight for game "abc"
    When the player submits another turn for game "abc"
    Then the response status is 409
    And the error body contains code "conflict"

  Scenario: AC-25.5 — Credential stuffing detection
    Given an IP address has made 6 failed login attempts in 5 minutes
    When the IP makes another authentication request
    Then the request is blocked for 15 minutes
    And an abuse_detected event is logged with pattern "credential_stuffing"

  Scenario: AC-25.6 — Rate limit fallback on Redis failure
    Given Redis is unavailable
    When a player submits a request
    Then in-memory rate limiting is applied
    And a warning is logged indicating degraded rate limiting
    And the /health endpoint reports Redis as degraded

  # [v2 — Streaming] v1 rate limiting runs as ASGI middleware before the SSE
  # endpoint handler; once a connection is accepted, there is no mechanism to
  # check rate limits mid-stream. True stream-aware rate limiting requires v2.
  Scenario: AC-25.7 — Active stream not interrupted
    Given a player is receiving an SSE narrative stream
    And the player exceeds their rate limit
    When the active stream is checked
    Then the stream continues to completion
    And subsequent NEW requests are rate limited

  Scenario: AC-25.8 — Escalating anti-abuse cooldown
    Given a source IP has been rate-limited 3 times in 10 minutes
    When the same IP makes another request
    Then the cooldown period is doubled compared to the initial window
    And the abuse escalation is logged
```

### Criteria Checklist
- [ ] **AC-25.1**: Normal gameplay unaffected by rate limits
- [ ] **AC-25.2**: 429 response with proper headers when limit exceeded
- [ ] **AC-25.3**: Rate limit headers present on all responses
- [ ] **AC-25.4**: Concurrent turn submission prevented with 409
- [ ] **AC-25.5**: Credential stuffing detected and blocked
- [ ] **AC-25.6**: In-memory fallback when Redis is down
- [ ] **AC-25.7**: Active SSE streams not interrupted by rate limiting
- [ ] **AC-25.8**: Escalating cooldowns for repeated violations

---

## 8. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|------|-------------|----------|
| S10 (API & Streaming) | Extends | Rate limiting is applied as middleware before route handlers. SSE streaming connections are rate limited at connection time, not per-event. |
| S11 (Identity & Sessions) | Requires | Player identity (session token) is needed for per-player rate limiting. S25 does not define its own auth — it reads the session from S11's mechanism. |
| S12 (Persistence) | Requires | Redis is used for rate limit state. S25 follows S12's Redis connection patterns and failover behavior. |
| S23 (Error Handling) | Cooperates | 429 responses use S23's error envelope. Rate limit unavailability is reported in S23's health endpoint. |
| S24 (Content Moderation) | Cooperates | Content moderation runs AFTER rate limiting. A rate-limited request never reaches moderation. |
| S26 (Admin Tooling) | Cooperates | S26 provides operator API for viewing and managing rate limits (FR-25.15). |

---

## 9. Open Questions

| # | Question | Impact | Resolution needed by |
|---|----------|--------|---------------------|
| Q-25.1 | Should rate limits reset on server restart, or should they persist in Redis? | Redis-backed limits persist. In-memory limits reset. Is this acceptable asymmetry? | Before implementation |
| Q-25.2 | Should SSE connections count against the per-player request limit, or have a separate budget? | Currently specified as separate (5 connections/min). Need to validate this is sufficient for reconnection scenarios. | Before implementation |
| Q-25.3 | Should whitelisted IPs be stored in Redis or in application config? | Redis allows dynamic changes. Config is simpler but requires restart (unless hot-reloaded). | Before implementation |

---

## 10. Out of Scope

- **DDoS mitigation at infrastructure level** — Rate limiting is application-level. Infrastructure-level protection (CDN, WAF, IP blocking at load balancer) is out of scope for v1. — Recommended for production deployment.
- **Per-player billing or usage quotas** — v1 has no payment system. All players have the same limits. — Deferred.
- **Geographic rate limiting** — No geo-based rate differentiation. — Deferred.
- **API key-based rate limiting** — v1 uses session tokens only. API keys for external integrations are deferred. — Deferred.
- **Adaptive rate limits based on server load** — Limits are static (configurable, not dynamic). — Deferred.

---

## Appendix

### A. Glossary

| Term | Definition |
|---|---|
| **Sliding window** | A rate limiting algorithm that smooths request counting over a rolling time period, avoiding burst allowances at fixed window boundaries. |
| **Rate limit tier** | The scope at which a rate limit is applied: per-player (session-based) or per-IP. |
| **Cooldown** | A period during which a rate-limited source must wait before retrying. Escalating cooldowns increase the wait after repeated violations. |
| **Credential stuffing** | An automated attack where stolen username/password pairs are tried against a service. |
| **In-flight** | A request that has been accepted for processing but has not yet completed. |

---

## v1 Closeout (Non-normative)

> This section is retrospective and non-normative. It documents what shipped in the v1
> baseline, what was verified, what gaps were found, and what is deferred to v2.

### What Shipped

- **`RateLimitMiddleware`** — per-endpoint sliding-window rate limiter in
  `src/tta/api/middleware.py`; uses `RedisRateLimiter` (when Redis is reachable) or
  `InMemoryRateLimiter` (fallback) from `src/tta/resilience/rate_limiter.py`
- **Endpoint groups** — `EndpointGroup` enum with distinct limits for turn submission,
  auth, and default endpoints
- **`429` response shape** — `_build_429_response` returns JSON with `Retry-After` header
- **Rate-limit headers** — `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
  `X-RateLimit-Reset` headers on all rate-limited responses
- **Admin reset** — `/admin/rate-limits/player/{player_id}/reset` allows per-player
  override; `/admin/rate-limits/ip/{ip_address}/unblock` for IP-level reset (AC-26.7)

### Evidence

- `tests/unit/resilience/test_rate_limiter.py` — AC-25.1 through AC-25.5 covered:
  window tracking, 429 response, Retry-After header, session key extraction, endpoint
  classification

### Gaps Found in v1

1. **Redis limiter not shared across multiple workers** — `RedisRateLimiter` is used
   when Redis is reachable, but each worker process maintains its own in-memory sliding
   window alongside Redis; multi-instance deployments may inconsistently share state
2. **Abuse pattern detection is basic** — `AbuseDetector` in `RateLimitMiddleware`
   detects `RAPID_FIRE` and `CREDENTIAL_STUFFING` patterns, but no IP reputation
   checking, volumetric anomaly detection, or external threat feed integration exists
3. **No ban / lockout escalation** — repeated violations increment violation counters but
   do not escalate to a temporary ban or block

### Deferred to v2

| Feature | Reason |
|---------|--------|
| Redis-backed distributed rate limiter | Required for multi-instance v2 |
| Abuse pattern detection | v2 anti-abuse work |
| Escalating lockout | v2 trust & safety |

### Lessons for v2

- In-memory rate limiting is acceptable for v1 single-process; replace it before
  multi-instance or horizontal scaling in v2
- The `EndpointGroup` abstraction is clean; keep it and add new groups per new v2 endpoint
  cluster
