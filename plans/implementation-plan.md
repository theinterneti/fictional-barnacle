# TTA — Unified Implementation Plan

> **Purpose**: Single consolidated view of all remaining implementation work.
> Built from the 7 component plans and the current wave-progress state.
> **Current state**: Wave 28 complete (S09 prompt management, PR #117, 1728 tests, 0 pyright errors).
> **Next candidates**: Waves 29–34 below.

---

## Completed Waves (Reference)

| Wave | Spec(s) | Summary |
|------|---------|---------|
| 1 | Foundation | Scaffold, models, DB migrations, Docker, CI |
| 2 | S07, S08 | LLM client, turn pipeline, context budget, cost tracking |
| 3 | S02, S04, S13 | World model, Neo4j schema, Genesis onboarding |
| 4–6 | S05, S06 | Choice/consequence, character system |
| 7 | S14, S15, S16 | Docker, CI, observability (structlog, OTel, Langfuse, Prometheus) |
| 8 | S23, S24, S25 | Error taxonomy, content moderation, rate limiting |
| 9 | S27 | Game lifecycle: auto-save, resume, listing, deletion |
| 10–22 | S07, S05 | Context budget, cost caps, consequence improvements |
| 28 | S09 | Prompt management: FilePromptRegistry, safety preamble, fragment composition |

---

## Remaining Work

### Wave 29 — S10: API & Streaming Compliance

**Plan**: `plans/api-and-sessions.md §1–3`
**Specs**: S10, S23 (cross-reference)
**Open issues already tracking this**: #128, #129, #130

#### Phase 29a — S10 Spec Reconciliation
Resolve the three-way contract discrepancy between S10, S23, and S27 for error envelopes, game lifecycle state transitions, and health endpoint paths. Ensure all existing tests, routes, and error handlers match the canonical contract.

**Acceptance Criteria:**
- [ ] AC-10.09 — Error responses use `{error_code, message, correlation_id}` envelope on all routes
- [ ] AC-10.10 — Health endpoints are `/api/v1/health` (liveness) and `/api/v1/health/ready` (readiness)
- [ ] S27 FR-27.16 — DELETE game → soft-delete to `abandoned` (not `ended`)
- [ ] All existing unit + integration tests pass after reconciliation

**Depends on**: #128

#### Phase 29b — SSE Event Taxonomy Alignment
Align the SSE event stream with the canonical taxonomy from `plans/system.md §4` and `plans/llm-and-pipeline.md §3.3`. Events: `turn_start`, `narrative_token`, `world_update`, `choice_presented`, `turn_complete`, `error`.

**Acceptance Criteria:**
- [ ] AC-10.02 — SSE events match the canonical taxonomy (type + data fields)
- [ ] AC-10.03 — `turn_complete` event carries final world-state diff
- [ ] `choice_presented` event carries generated choice list
- [ ] `error` event carries `{error_code, message}` and triggers SSE stream close

**Depends on**: Phase 29a

#### Phase 29c — SSE Replay & Reconnect
Implement Last-Event-ID reconnect: deliver buffered events from the completed-turn snapshot when a client reconnects after disconnect.

**Acceptance Criteria:**
- [ ] AC-10.04 — Client that sends `Last-Event-ID` receives missed events from turn buffer
- [ ] AC-10.05 — Client that reconnects mid-processing joins the live stream
- [ ] AC-10.06 — Turn snapshot stored in Redis with TTL = 30 minutes
- [ ] Integration test: `tests/integration/test_sse_reconnect.py`

**Depends on**: Phase 29b

---

### Wave 30 — S11: Player Identity & Sessions

**Plan**: `plans/api-and-sessions.md §4–6`
**Specs**: S11

#### Phase 30a — Anonymous JWT Authentication
Implement the anonymous-first auth flow: `POST /api/v1/players` issues a signed JWT (no PII required), `GET /api/v1/players/me` verifies it, dependency `get_current_player` wired into all protected routes.

**Acceptance Criteria:**
- [ ] AC-11.01 — Anonymous player can register without providing any PII
- [ ] AC-11.02 — Registration requires consent version, required categories, and age confirmation
- [ ] AC-11.03 — JWT issued on registration; all game routes require valid JWT
- [ ] AC-11.04 — Token expiry enforced; expired tokens return 401 `auth_required`
- [ ] `get_current_player` FastAPI dependency raises `auth_required` on missing/invalid/expired token

**Depends on**: Wave 29

#### Phase 30b — Session Lifecycle & Token Management
Token refresh, player profile retrieval, session expiry, and the full player delete (GDPR right-to-erasure) flow.

**Acceptance Criteria:**
- [ ] AC-11.05 — `POST /api/v1/players/token/refresh` issues a new JWT before expiry
- [ ] AC-11.06 — `DELETE /api/v1/players/{id}` anonymises all player data (GDPR erase)
- [ ] AC-11.07 — Active games belonging to deleted player are transitioned to `abandoned`
- [ ] AC-11.08 — `GET /api/v1/players/me` returns profile without PII for anonymous players

**Depends on**: Phase 30a

#### Phase 30c — BDD Scenarios: Auth & Session Lifecycle
Wire the BDD step definitions for S11 scenarios into the integration test suite.

**Acceptance Criteria:**
- [ ] BDD: Anonymous player starts a game (S11 AC-11.01) — `tests/bdd/step_defs/test_anonymous_play.py`
- [ ] BDD: Game lifecycle transitions (S11 AC-11.04–08) — `tests/bdd/step_defs/test_game_lifecycle.py`
- [ ] All BDD scenarios green in CI

**Depends on**: Phase 30a, Phase 30b

---

### Wave 31 — S12: Persistence Deferred ACs

**Plan**: `plans/api-and-sessions.md §7`
**Specs**: S12
**Context**: AC-12.04, AC-12.06, AC-12.08 were explicitly deferred in Wave 27 (PR #115).

#### Phase 31a — Game State Snapshots (AC-12.04)
Persist a full game-state snapshot at configurable intervals so save/load can reconstruct state without replaying all events.

**Acceptance Criteria:**
- [ ] AC-12.04 — Game state snapshot written to PostgreSQL `game_snapshots` table every N turns (configurable)
- [ ] Snapshot includes: world context hash, inventory state, relationship scores, turn count
- [ ] Resume flow prefers snapshot over full event replay when snapshot age < threshold

**Depends on**: Wave 30

#### Phase 31b — Neo4j Graph Reconstruction (AC-12.06)
Fall back to reconstructing the Neo4j world graph from PostgreSQL event log when the graph is empty or stale.

**Acceptance Criteria:**
- [ ] AC-12.06 — On game resume, if Neo4j graph is empty for a session, rebuild from `world_events` table
- [ ] Reconstruction is idempotent (safe to re-run)
- [ ] Integration test: `tests/integration/test_degraded_mode.py` — Redis-down and Neo4j-cold paths

**Depends on**: Phase 31a

#### Phase 31c — Graph Operation Latency Metrics (AC-12.08)
Instrument Neo4j reads and writes with Prometheus histograms for the latency SLA.

**Acceptance Criteria:**
- [ ] AC-12.08 — `neo4j_operation_duration_seconds` histogram exposed at `/metrics`
- [ ] P95 Neo4j read latency tracked (SLA: < 50 ms)
- [ ] Histogram labels: `operation` (read/write), `query_type`

**Depends on**: Phase 31a

---

### Wave 32 — S26: Admin & Operator Tooling

**Plan**: `plans/ops.md §5`
**Specs**: S26

#### Phase 32a — Admin Authentication & Route Guard
Implement operator-only auth: separate `X-Admin-Token` header verified via constant-time comparison against `ADMIN_TOKEN` env var. `get_admin_token` dependency wired into all `/admin/` routes.

**Acceptance Criteria:**
- [ ] AC-26.1 — All admin routes return 401 without valid `X-Admin-Token`
- [ ] AC-26.2 — Admin token validated via constant-time comparison (no timing attacks)
- [ ] Admin routes prefixed `/api/v1/admin/`

**Depends on**: Wave 30

#### Phase 32b — Admin Player Management
List players, view player details, and suspend/unsuspend player accounts.

**Acceptance Criteria:**
- [ ] AC-26.3 — `GET /admin/players` returns paginated player list with filters
- [ ] AC-26.4 — `GET /admin/players/{id}` returns player profile + game history
- [ ] AC-26.5 — `POST /admin/players/{id}/suspend` sets account status to `suspended`
- [ ] AC-26.6 — `POST /admin/players/{id}/unsuspend` restores active status

**Depends on**: Phase 32a

#### Phase 32c — Admin Game Management & Termination
List all games, terminate active games forcefully, and purge expired/abandoned sessions.

**Acceptance Criteria:**
- [ ] FR-26.12 / AC-26.5 — `POST /admin/games/{id}/terminate` sets game state to `completed`
- [ ] `GET /admin/games` — paginated list with status/player filters
- [ ] `DELETE /admin/games/{id}` — hard-delete game and all associated data (operator tool)

**Depends on**: Phase 32a

#### Phase 32d — Audit Log Endpoint
Expose the moderation audit trail for admin review.

**Acceptance Criteria:**
- [ ] `GET /admin/audit` — returns paginated moderation audit events
- [ ] Filterable by player_id, game_id, flag_type, date range
- [ ] Audit events include: timestamp, player_id, game_id, flag type, content hash

**Depends on**: Phase 32b

---

### Wave 33 — S28: Performance & Scaling

**Plan**: `plans/ops.md §6`
**Specs**: S28

#### Phase 33a — Latency Budget Instrumentation
Add histogram metrics that enforce and surface the v1 latency SLAs.

**Acceptance Criteria:**
- [ ] AC-28.01 — P95 end-to-end turn latency ≤ 2000 ms tracked via `turn_latency_seconds` histogram
- [ ] AC-28.02 — LLM call latency histogram with `model` + `stage` labels
- [ ] AC-28.03 — Database query latency histograms for PostgreSQL and Neo4j
- [ ] Histogram buckets: 0.05, 0.1, 0.25, 0.5, 1, 2, 5 seconds

**Depends on**: Wave 31

#### Phase 33b — Load Testing Harness
Implement the `make test-load` target with k6 or Locust scenarios for baseline throughput validation.

**Acceptance Criteria:**
- [ ] AC-28.04 — `make test-load` runs a configurable ramp scenario (e.g. 10 concurrent players)
- [ ] Load test validates p95 turn latency SLA at baseline load
- [ ] CI job (optional, manual trigger) runs load tests against a staging stack

**Depends on**: Phase 33a

---

### Wave 34 — BDD Wave 4 Scenarios

**Plan**: `plans/api-and-sessions.md §8`
**Specs**: S10, S11

#### Phase 34a — SSE & Turn Flow BDD
Wire missing BDD step definitions for S10 scenarios.

**Acceptance Criteria:**
- [ ] BDD: Turn submission and streaming (S10 AC-10.01) — `tests/bdd/step_defs/test_turn_flow.py`
- [ ] BDD: Rate limiting (S10 AC-10.07–08) — `tests/bdd/step_defs/test_rate_limiting.py`
- [ ] BDD: Error response shape (S10 AC-10.09–10) — `tests/bdd/step_defs/test_error_shapes.py`
- [ ] BDD: Player cannot access other's game (S10 AC-10.12) — `tests/bdd/step_defs/test_access_control.py`

**Depends on**: Wave 29, Wave 30

---

## Dependency Graph

```
Wave 29 (S10 API)
  └── Wave 30 (S11 Auth)
        └── Wave 31 (S12 Persistence deferred)
              └── Wave 33 (S28 Performance)
        └── Wave 32 (S26 Admin)
  └── Wave 34 (BDD) ←─ also depends on Wave 30
```

## Out of Scope (v1)

- S18–S22 (future stubs — no implementation planned)
- Multi-version prompt registry (S09 deferred to v2)
- Runtime prompt activation without deploy (S09 deferred)
- Automated A/B testing with cohort assignment
- `tta-worker` container / external job queue

---

*Last updated: auto-generated from plans/ at Wave 28 complete.*
