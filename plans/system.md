# System Technical Plan

> **Phase**: SDD Phase 2 — Technical Plan
> **Scope**: Cross-cutting decisions for the entire TTA system
> **Input specs**: S00 (Charter), S01-S17 (all v1 specs)
> **Status**: 📝 Draft
> **Last Updated**: 2026-04-07

---

## 1. Technology Stack and Frameworks

### 1.1 — Core Technologies

| Layer | Technology | Version | Rationale |
|-------|-----------|---------|-----------|
| **Language** | Python | ≥ 3.12 | AI/ML ecosystem, async/await, typing |
| **Package manager** | uv | latest | Fast, lockfile-based, replaces pip+venv |
| **API framework** | FastAPI | ≥ 0.135 | Async, typed, **native SSE** (`fastapi.sse.EventSourceResponse`), auto OpenAPI docs |
| **ASGI server** | Uvicorn | ≥ 0.30 | Standard, `--reload` for dev |
| **LLM gateway** | LiteLLM | ≥ 1.50 | Library mode (not proxy). Unified API, streaming, fallback, cost tracking |
| **World graph** | Neo4j Community | 5.x | Native graph for world state. Cypher queries. CE is sufficient for v1 scale. |
| **Relational DB** | PostgreSQL | 16+ | Player data, sessions, transcripts. Use everywhere — including dev. No SQLite. |
| **Session cache** | Redis | 7+ | Active session state, SSE pub/sub. Ephemeral only — never the source of truth. Use `redis.asyncio` (redis-py ≥ 5.0) — NOT standalone `aioredis`. |
| **ORM / query** | SQLModel | ≥ 0.0.38 | Thin Pydantic+SQLAlchemy 2.0 layer. Raw asyncpg for hot paths if needed. |
| **Neo4j driver** | neo4j (Python) | ≥ 6.0 | Official async driver (`AsyncGraphDatabase.driver()`) |
| **Resilience** | tenacity | ≥ 9.0 | Retry with backoff. Do NOT build custom retry/circuit-breaker logic. |
| **SQL driver (app)** | asyncpg | latest | Async Postgres driver for FastAPI runtime |
| **SQL driver (migrations)** | psycopg[binary] | latest | Sync Postgres driver for Alembic CLI commands |
| **HTTP client** | httpx | ≥ 0.27 | Async HTTP for internal calls and testing |

### 1.2 — Observability

| Tool | Purpose | Mode |
|------|---------|------|
| **Langfuse** | LLM tracing, prompt versioning, cost tracking | Self-hosted (Docker) in all environments. **SDK v4** — use `@observe()` decorator (NOT custom `@trace_llm`). Self-hosted stack requires Clickhouse + Redis + MinIO — use Docker Compose profiles (`--profile langfuse`). Cloud free tier is opt-in for convenience but sends prompts off-machine — see §5.2 for privacy constraints. |
| **structlog** | Application logging | Structured JSON to stdout |
| **OpenTelemetry** | Distributed tracing (non-LLM) | OTLP exporter to Langfuse or Jaeger |
| **Prometheus** | Metrics (request latency, error rates) | Scraped from `/metrics` endpoint |

### 1.3 — Development Tooling

| Tool | Purpose | Configuration |
|------|---------|---------------|
| **ruff** | Linting + formatting | 88-char lines, `py312`, select `E,W,F,I,B,C4,UP` |
| **pyright** | Type checking | `standard` mode |
| **pytest** | Testing | `asyncio_mode = "auto"` |
| **pytest-bdd** | Gherkin test execution | For user-visible behavior ACs only |
| **pytest-cov** | Coverage reporting | 80% target for game-critical paths |
| **Docker Compose** | Local infrastructure | Neo4j + Postgres + Redis |

### 1.4 — Explicit Exclusions

| Technology | Why excluded |
|-----------|-------------|
| **LangGraph** | The turn pipeline is a linear 4-stage flow. LangGraph adds abstraction before it adds value. If we need cyclic workflows, conditional branching, or checkpointing later, adopt then. |
| **LangChain** | Too much abstraction, too many hidden behaviors. We use LiteLLM for LLM calls directly. |
| **Ink / Twine** | TTA's differentiator is emergent narrative from world simulation, not pre-authored branching stories. The world graph IS the story structure. |
| **SQLite** | No dev/prod parity issues. Postgres in all environments via Docker. |
| **Dolt** | Time-travel queries aren't needed in v1. Postgres is simpler. |
| **WebSocket** | SSE is sufficient for v1's unidirectional streaming. WebSocket adds complexity for multiplayer (future). |
| **Custom circuit breakers** | tenacity handles retry. If a model is down, LiteLLM's fallback chain handles failover. |
| **Behave** | pytest-bdd integrates with the existing pytest ecosystem. Behave is a separate test runner. |

---

## 2. Architecture and Boundaries

### 2.1 — Component Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Application                    │
│                                                          │
│  ┌──────────┐  ┌───────────────────────────────────┐     │
│  │   API    │  │        Turn Pipeline               │     │
│  │  Routes  │──│  ┌───────┐ ┌─────────┐ ┌────────┐ │     │
│  │          │  │  │ Input │→│ Context │→│ Genera- │ │     │
│  │ /games   │  │  │ Under-│ │ Assembly│ │  tion  │─┼──┐  │
│  │ /turns   │  │  │ stand │ │         │ │        │ │  │  │
│  │ /health  │  │  └───────┘ └────┬────┘ └────────┘ │  │  │
│  └──────────┘  │                 │                  │  │  │
│       │        └─────────────────┼──────────────────┘  │  │
│       │                          │                     │  │
│  ┌────┴─────┐  ┌────────────┐  ┌┴───────────┐  ┌─────┴┐ │
│  │ Session  │  │   World    │  │    LLM     │  │ SSE  │ │
│  │ Manager  │  │   Service  │  │   Client   │  │Stream│ │
│  │ (Redis)  │  │  (Neo4j)   │  │ (LiteLLM)  │  │      │ │
│  └──────────┘  └────────────┘  └────────────┘  └──────┘ │
│       │              │                │                   │
│  ┌────┴──────────────┴────────────────┴────────────────┐ │
│  │              Persistence Layer                       │ │
│  │  PostgreSQL (players, sessions, transcripts)         │ │
│  │  Neo4j (world graph)                                 │ │
│  │  Redis (active sessions — ephemeral)                 │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌──────────────────────────────────────────────────────┐ │
│  │              Safety Seams (interfaces only in v1)     │ │
│  │  pre_generation_hook() → identity function            │ │
│  │  post_generation_hook() → identity function           │ │
│  │  audit_log → append every turn to Postgres            │ │
│  └──────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
         │              │               │
    ┌────┴────┐   ┌─────┴─────┐   ┌────┴────┐
    │Postgres │   │   Neo4j   │   │  Redis  │
    │  (SQL)  │   │  (Graph)  │   │ (Cache) │
    └─────────┘   └───────────┘   └─────────┘
```

### 2.2 — Single Process, Single Container

TTA v1 runs as **one FastAPI process** in **one container**. There are no microservices, no message queues between components, no separate worker processes.

Why:
- Eliminates network hops between components
- Simplifies deployment, debugging, and tracing
- v1 targets hundreds of concurrent players, not thousands
- If we need to scale, we scale the databases first (they're the bottleneck), not the app server

The container talks to 3 external services (Postgres, Neo4j, Redis) via Docker networking.

### 2.3 — Integration Boundaries

| Boundary | Inbound contract | Outbound contract |
|----------|-----------------|-------------------|
| **HTTP API ↔ Pipeline** | `TurnRequest` (Pydantic model) | `AsyncIterator[SSEEvent]` |
| **Pipeline ↔ LLM** | `LLMRequest` (model role, messages, params) | `AsyncIterator[str]` (token stream) |
| **Pipeline ↔ World** | `WorldQuery` (location_id, depth, filters) | `WorldContext` (facts, NPCs, items) |
| **Pipeline ↔ Persistence** | Repository protocol (get/save/query) | Domain models |
| **API ↔ Client** | REST (JSON) + SSE (event stream) | N/A (client is external) |
| **Safety seams** | `SafetyHook` protocol (callable) | `SafetyResult` (allow/flag/block) |

### 2.4 — The Safety Seam Architecture

Full safety systems (S18, S19) are deferred. But the **seam points** must exist in v1 so we don't rewrite the pipeline later.

```python
# Safety hook protocol — v1 implementations are pass-through
class SafetyHook(Protocol):
    async def check(self, content: str, context: TurnContext) -> SafetyResult: ...

class SafetyResult:
    action: Literal["allow", "flag", "block"]
    reason: str | None = None

# In v1, both hooks are no-ops:
class PassthroughHook:
    async def check(self, content, context):
        return SafetyResult(action="allow")
```

Four seam points in the pipeline:
1. **Pre-input**: After parsing, before context assembly. Inspects player input.
2. **Pre-generation**: After context assembly, before LLM call. Inspects the full prompt.
3. **Post-generation**: After LLM response, before delivery. Inspects generated text.
4. **Stream interrupt**: Interface exists but is a **no-op in v1** (see note below).

**v1 streaming architecture: buffer-then-stream.** The generation stage collects the full
LLM response into a buffer. The post-generation hook inspects the complete text. Only after
approval does the delivery stage stream tokens to the client via SSE. This means v1 has
slightly higher time-to-first-token (buffer delay) but makes safety inspection unambiguous.
Mid-stream interruption requires chunk-level moderation — deferred to when S18/S19 are
implemented.

### 2.5 — Project Structure

```
fictional-barnacle/
├── src/
│   └── tta/
│       ├── __init__.py          # Package version
│       ├── config.py            # Pydantic Settings (env vars)
│       ├── api/
│       │   ├── __init__.py
│       │   ├── app.py           # FastAPI application factory
│       │   ├── routes/
│       │   │   ├── games.py     # /games endpoints
│       │   │   ├── turns.py     # /games/{id}/turns
│       │   │   └── health.py    # /health, /metrics
│       │   ├── sse.py           # SSE event formatting + streaming
│       │   └── middleware.py    # CORS, request ID, error handlers
│       ├── pipeline/
│       │   ├── __init__.py
│       │   ├── orchestrator.py  # Wire 4 stages, manage TurnState
│       │   ├── input_understanding.py
│       │   ├── context_assembly.py
│       │   ├── generation.py
│       │   └── delivery.py
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── client.py        # LiteLLM wrapper, model roles
│       │   ├── roles.py         # Model role definitions
│       │   └── testing.py       # Deterministic mock for CI
│       ├── world/
│       │   ├── __init__.py
│       │   ├── service.py       # World query interface
│       │   ├── graph.py         # Neo4j Cypher operations
│       │   └── seed.py          # World template loading
│       ├── genesis/
│       │   ├── __init__.py
│       │   └── lite.py          # Genesis-lite: 2-3 prompts → world seed
│       ├── models/
│       │   ├── __init__.py
│       │   ├── turn.py          # TurnState, TurnRequest, TurnResult
│       │   ├── game.py          # GameState, GameSession
│       │   ├── world.py         # WorldContext, Location, NPC, Item
│       │   ├── player.py        # Player, PlayerProfile
│       │   └── events.py        # SSE event types
│       ├── persistence/
│       │   ├── __init__.py
│       │   ├── postgres.py      # SQLModel repos (players, sessions, turns)
│       │   ├── redis_session.py # Active session cache
│       │   └── repositories.py  # Repository protocols
│       └── safety/
│           ├── __init__.py
│           ├── hooks.py         # SafetyHook protocol + PassthroughHook
│           └── audit.py         # Turn audit logger
├── tests/
│   ├── conftest.py              # Shared fixtures, DB setup
│   ├── unit/
│   │   ├── pipeline/
│   │   ├── llm/
│   │   ├── world/
│   │   └── models/
│   ├── integration/
│   │   ├── test_pipeline_e2e.py
│   │   ├── test_neo4j.py
│   │   └── test_postgres.py
│   └── bdd/
│       ├── features/            # .feature files (Gherkin)
│       └── step_defs/           # Step implementations
├── specs/                       # Functional specifications (already written)
├── plans/                       # Technical plans (this directory)
├── docker-compose.yml           # Production-like services
├── docker-compose.override.yml  # Dev: hot reload, debug ports
├── Dockerfile                   # Multi-stage: build + runtime
├── pyproject.toml
├── Makefile
├── .env.example
├── .python-version              # 3.12
└── .github/
    └── workflows/
        └── ci.yml
```

---

## 3. Data Models and Schemas

### 3.1 — Persistence Ownership Matrix

Every piece of data has exactly one source of truth. This table is authoritative.

| Entity | Source of Truth | Cache | Retention | Access Pattern |
|--------|---------------|-------|-----------|----------------|
| Player profile | PostgreSQL | — | Until deletion request | CRUD by player ID |
| Player sessions (auth) | PostgreSQL | — | Until expiry or logout | Lookup by token |
| Game session metadata | PostgreSQL | Redis (active only) | Per-game lifetime | Lookup by session ID |
| Turn transcript | PostgreSQL | — | Per-game lifetime | Append-only, query by session |
| World events log | PostgreSQL | — | Per-game lifetime | Append per turn, query recent by session |
| World graph (locations, NPCs, items) | Neo4j | — | Per-game lifetime | Cypher traversal queries |
| Active game state snapshot | Redis | — | Ephemeral (rebuilt from DB on miss) | Get/set by session ID |
| LLM call traces | Langfuse | — | 90 days default | Langfuse UI |
| Prompt templates | Code/config files | — | Versioned with deploys | Loaded at startup |
| System configuration | Environment variables | — | Per-deploy | Read at startup |

### 3.2 — PostgreSQL Schema (Core Tables — Normative)

> **These table definitions are normative.** Component plans may add columns or
> supplementary tables but must not alter the structure below. If a component plan
> needs a schema change here, it must be proposed as an amendment to this document.

```sql
-- Players (v1: anonymous with handle only — see Auth Scope below)
CREATE TABLE players (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    handle      TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Player sessions (server-side, opaque tokens)
CREATE TABLE player_sessions (
    token       TEXT PRIMARY KEY,                  -- Opaque session token (32-byte hex)
    player_id   UUID NOT NULL REFERENCES players(id),
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_player_sessions_player ON player_sessions(player_id);

-- Game sessions
CREATE TABLE game_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id   UUID NOT NULL REFERENCES players(id),
    status      TEXT NOT NULL DEFAULT 'active',  -- active, paused, completed
    world_seed  JSONB NOT NULL,                  -- Genesis output
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Turn transcripts (append-only, durable record of each turn)
CREATE TABLE turns (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id        UUID NOT NULL REFERENCES game_sessions(id),
    turn_number       INTEGER NOT NULL,
    idempotency_key   UUID,                        -- Client-generated. Prevents duplicate submissions.
    status            TEXT NOT NULL DEFAULT 'processing', -- processing | complete | failed
    player_input      TEXT NOT NULL,
    parsed_intent     JSONB,                       -- Stage 1 output
    world_context     JSONB,                       -- Stage 2 snapshot
    narrative_output  TEXT,                         -- Stage 3 output (NULL while processing)
    model_used        TEXT,                         -- e.g. "claude-sonnet-4-20250514"
    latency_ms        INTEGER,
    token_count       JSONB,                       -- {prompt: N, completion: M}
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ,
    UNIQUE (session_id, turn_number),
    UNIQUE (session_id, idempotency_key)
);

-- World events log (source of truth for get_recent_events())
-- Records state changes produced by each turn for narrative continuity.
CREATE TABLE world_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES game_sessions(id),
    turn_id         UUID NOT NULL REFERENCES turns(id),
    event_type      TEXT NOT NULL,                  -- npc_moved, item_taken, location_changed, etc.
    entity_id       TEXT NOT NULL,                  -- Neo4j node ID of the affected entity
    payload         JSONB NOT NULL,                 -- Change details (from/to, old/new state)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_world_events_session ON world_events(session_id, created_at DESC);
```

### 3.3 — Neo4j World Graph Schema (Minimal v1)

```
(:Location {id, name, description, type, visited: bool})
(:NPC {id, name, description, disposition, alive: bool})
(:Item {id, name, description, portable: bool, hidden: bool})
(:Player {session_id})

(:Location)-[:CONNECTS_TO {direction, traversable}]->(:Location)
(:NPC)-[:IS_AT]->(:Location)
(:Item)-[:IS_AT]->(:Location)
(:Item)-[:CARRIED_BY]->(:Player)
(:Player)-[:IS_AT]->(:Location)
(:NPC)-[:KNOWS_ABOUT]->(:NPC|:Item|:Location)
```

Full schema specification in `plans/world-and-genesis.md`.

### 3.4 — Redis Key Patterns

```
session:{session_id}          → JSON GameState snapshot (TTL: 1 hour)
sse:{session_id}:stream       → Pub/sub channel for SSE events
```

Redis is ephemeral. If a key is missing, reconstruct from PostgreSQL + Neo4j. This is a cache, not a database.

**Concurrent turn prevention** is NOT in Redis — it uses the Postgres `turns` table
(see §4.1). Redis holds only ephemeral cache and pub/sub channels.

---

## 4. Interfaces and Contracts

### 4.1 — REST API Endpoints

| Method | Path | Request | Response | Auth | Description |
|--------|------|---------|----------|------|-------------|
| `POST` | `/api/v1/games` | `CreateGameRequest` | `GameSession` | Session token | Create new game, run Genesis-lite |
| `GET` | `/api/v1/games/{id}` | — | `GameState` | Session token | Get current game state |
| `POST` | `/api/v1/games/{id}/turns` | `TurnRequest` | `202 Accepted` + `{turn_id, stream_url}` | Session token | Submit turn (async). Returns a turn ID and URL for the SSE stream. |
| `GET` | `/api/v1/games/{id}/stream` | — | SSE stream | Session token | Long-lived SSE connection. Streams events for the current/next turn. Client connects once and keeps listening. |
| `POST` | `/api/v1/games/{id}/save` | — | `SaveConfirmation` | Session token | Save game state |
| `POST` | `/api/v1/games/{id}/resume` | — | `GameState` | Session token | Resume saved game |
| `GET` | `/api/v1/health` | — | `HealthStatus` | None | Liveness + dependency checks |
| `GET` | `/api/v1/health/ready` | — | `ReadyStatus` | None | Readiness (all deps connected) |

**Turn submission flow (aligned with S10):**
1. Client opens `GET /api/v1/games/{id}/stream` (SSE, long-lived)
2. Client submits `POST /api/v1/games/{id}/turns` with `{input, idempotency_key}`
3. Server creates a durable `turn` record (status=`processing`), returns `202 {turn_id}`
4. Pipeline processes the turn and streams events over the existing SSE connection
5. `turn_complete` event signals the end; turn record updated to status=`complete`

**Idempotency:** The `idempotency_key` (client-generated UUID) is stored on the turn record.
Duplicate submissions with the same key return the existing `turn_id` without reprocessing.

**Concurrent turn prevention:** Enforced via a Postgres row-level check: `SELECT ... WHERE
session_id = $1 AND status = 'processing' FOR UPDATE`. If a turn is already in-flight for
this session, the server rejects with `409 Conflict`. This works even if Redis is down.

### 4.2 — SSE Event Schema

Events flow from server to client over the turn's SSE stream:

```
event: turn_start
data: {"turn_number": 5, "timestamp": "..."}

event: narrative_token
data: {"token": "The "}

event: narrative_token
data: {"token": "forest "}

event: narrative_token
data: {"token": "stirs..."}

event: world_update
data: {"changes": [{"type": "npc_moved", "npc_id": "...", "to": "..."}]}

event: turn_complete
data: {"turn_number": 5, "model_used": "claude-sonnet-4-20250514", "latency_ms": 2340}

event: error
data: {"code": "generation_failed", "message": "The story pauses momentarily..."}

event: keepalive
data: {}
```

**Reconnection contract (v1):** The client reconnects to `GET /stream`. If a turn was
in-flight, the server checks the durable `turns` table. If status is `complete`, it sends
a single `narrative_block` event with the full narrative output, then resumes listening for
the next turn. If status is `processing`, it reconnects to the live stream. Full SSE
reconnection with `Last-Event-ID` replay is post-MVP.

### 4.3 — TurnState (Pipeline Internal Contract — Normative)

> **This model is normative.** Component plans may add optional fields but must not
> remove or rename existing fields. The pipeline orchestrator depends on this contract.

The `TurnState` is the typed data structure that flows through the pipeline. Each stage reads and writes specific fields.

```python
class TurnState(BaseModel):
    """Immutable-ish state threaded through the pipeline."""

    # Set by API layer before pipeline starts
    session_id: str
    turn_number: int
    player_input: str
    game_state: GameState

    # Set by Stage 1: Input Understanding
    parsed_intent: ParsedIntent | None = None

    # Set by Stage 2: Context Assembly
    world_context: WorldContext | None = None
    narrative_history: list[str] = []

    # Set by Stage 3: Generation
    generation_prompt: str | None = None
    narrative_output: str | None = None
    model_used: str | None = None
    token_count: TokenCount | None = None

    # Set by Stage 4: Delivery
    delivered: bool = False
    latency_ms: int | None = None

    # Safety (pass-through in v1)
    safety_flags: list[str] = []
```

### 4.4 — LLM Client Interface

```python
class LLMClient(Protocol):
    """Interface for LLM calls. Implemented by LiteLLM wrapper."""

    async def generate(
        self,
        role: ModelRole,        # "generation" | "classification" | "extraction"
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> str:
        """Non-streaming generation. For classification/extraction."""
        ...

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> AsyncIterator[str]:
        """Streaming generation. For narrative output."""
        ...

class ModelRole(str, Enum):
    GENERATION = "generation"       # Narrative prose (high quality)
    CLASSIFICATION = "classification"  # Intent parsing (fast, cheap)
    EXTRACTION = "extraction"       # Entity/fact extraction (structured)
```

### 4.5 — World Query Interface

```python
class WorldService(Protocol):
    """Interface for world state queries. Implemented by Neo4j."""

    async def get_location_context(
        self, session_id: str, location_id: str, depth: int = 1
    ) -> LocationContext:
        """Get location + adjacent locations + NPCs + items."""
        ...

    async def get_recent_events(
        self, session_id: str, limit: int = 5
    ) -> list[WorldEvent]:
        """Get recent world state changes for narrative continuity.
        Source of truth: `world_events` Postgres table (see §3.2).
        """
        ...

    async def apply_world_changes(
        self, session_id: str, changes: list[WorldChange]
    ) -> None:
        """Apply state changes from a completed turn."""
        ...
```

---

## 5. Non-Functional Requirements and Constraints

### 5.1 — Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Time to first token (TTFT) | < 3 seconds p95 | From turn submission to first `narrative_token` SSE event |
| Full turn latency | < 15 seconds p95 | From turn submission to `turn_complete` event |
| API response (non-streaming) | < 200ms p95 | GET endpoints, health checks |
| Neo4j query latency | < 100ms p95 | Context assembly world queries |
| Concurrent sessions | ≥ 100 | Simultaneous active games on a single host |
| Memory per session | < 10 MB | Redis session state + in-flight pipeline state |

### 5.2 — Security Constraints

| Requirement | Implementation |
|-------------|---------------|
| No secrets in code | `.env` files, environment variables only. `.env` in `.gitignore`. |
| Session authentication | Opaque session token in cookie or `Authorization` header. No JWT for v1 — sessions are server-side (see `player_sessions` table in §3.2). |
| **Auth scope (v1)** | Anonymous play with a self-chosen handle. No email, no password, no OAuth. Players register by picking a unique handle and receive a session token. This is intentionally minimal — S11's full identity system (email/password, access/refresh tokens, account upgrades) is post-MVP. The `players` table and session model support adding auth later without schema changes. |
| Input length limits | Max 2,000 characters per turn input. Enforced at API layer. |
| Rate limiting | 10 turns per minute per session. 429 response on exceed. |
| CORS | Allow configured origins only. No `*` in production. |
| SQL injection | SQLModel/SQLAlchemy parameterized queries only. No raw string interpolation. |
| Cypher injection | Neo4j driver parameterized queries only. No f-string Cypher. |
| Prompt injection | Structural mitigation: system prompt separate from user input. No user text in system prompt. |
| **PII / Langfuse** | Turn content is logged to Langfuse for debugging. **Self-hosted Langfuse is the default** in all environments (Docker Compose service). Cloud Langfuse is opt-in — if enabled, the operator accepts that prompts (which include player input) leave the machine. Player handles are pseudonymous; no email or real names are collected in v1. See S17 for full privacy constraints. |

### 5.3 — Reliability

| Requirement | Approach |
|-------------|----------|
| LLM failure | 2-tier fallback within model family (e.g., Claude Sonnet → Haiku). If both fail, return a graceful in-narrative error ("The story pauses..."). Never crash. |
| Database failure | If Postgres is down, return 503. If Neo4j is down, return 503. If Redis is down, operate without cache (slower but functional — concurrent turn prevention uses Postgres, not Redis). |
| Graceful degradation | Langfuse down → skip tracing, continue serving. Redis down → skip cache, reconstruct from DB. Prometheus down → skip metrics. |
| Startup dependency checks | `/health/ready` verifies Postgres, Neo4j, Redis connections. App starts even if Langfuse is unreachable. |

### 5.4 — Scalability (v1 Posture)

v1 is a **single-host deployment**. Scaling strategy is documented for planning purposes but not implemented.

- **Vertical first**: Bigger host before adding complexity
- **Database scaling**: Neo4j AuraDB, managed Postgres, Redis cluster — all available as managed services
- **App scaling**: Stateless FastAPI behind a load balancer (no sticky sessions — all state is in databases)
- **NOT in v1**: Kubernetes, message queues, separate worker processes, CDN, edge deployment

### 5.5 — Compliance (v1)

- **NOT HIPAA**: TTA is a game, not healthcare. We do not collect PHI.
- **GDPR-aware**: Players can request data export and deletion. The mechanism exists but is manual in v1.
- **Content attribution**: AI-generated content is labeled as such. No claim of human authorship.
- **License**: TBD (open question from S00).

---

## 6. Resolved Architectural Questions

These were open in NEXT_STEPS.md. They are now decided.

### 6.1 — Model Fallback Strategy

**Decision: Same-family fallback as default.**

- Primary model family: configurable (e.g., Claude)
- Fallback: cheaper model in the same family (e.g., Claude Sonnet → Haiku)
- If entire family is down: return graceful in-narrative error, not a different family's output
- Classification/extraction roles: may use a different family (cheaper models fine here — tone doesn't matter)

**Rationale**: Cross-family fallback (Claude → GPT) produces jarring tone shifts mid-session. Same-family preserves voice consistency.

### 6.2 — World Graph Seeding Strategy

**Decision: Hybrid — template skeleton + LLM-generated flavor.**

Genesis-lite workflow:
1. Player answers 2-3 prompts (genre preference, character concept, "what kind of world?")
2. System selects a world template (pre-authored JSON: 3-5 locations, 2-3 NPCs, key items, connections)
3. LLM generates names, descriptions, and flavor text for all template entities
4. Loader creates the Neo4j graph from the enriched template

**Rationale**: Pure template is boring (identical worlds). Pure LLM is untestable and produces incoherent graphs. Hybrid gives structure + uniqueness.

### 6.3 — Turn Transcript Format

**Decision: Structured + raw (option 3).**

Every turn stores:
- Raw text (player input + narrative output) — for replay
- Structured metadata (parsed intent, world context snapshot, model used, tokens, latency) — for debugging and regression

Both live in the `turns` PostgreSQL table (see §3.2).

### 6.4 — SSE Reconnection

**Decision: Show completed turn on reconnect, using durable turn record.**

If a player disconnects mid-stream and reconnects:
- Client re-opens `GET /api/v1/games/{id}/stream`
- Server checks the latest turn in Postgres for this session
- If status is `complete`: sends a `narrative_block` event with the full `narrative_output`, then resumes listening
- If status is `processing`: reconnects to the live pub/sub stream in progress
- If status is `failed`: sends an `error` event with the failure reason
- No attempt to replay individual SSE events from a specific event ID
- Full `Last-Event-ID` reconnection is post-MVP (requires server-side event buffering)

### 6.5 — Frontend for v1

**Decision: Ship a minimal web client.**

A single HTML file with vanilla JS:
- Text input box
- Submit button
- SSE reader that appends tokens to a narrative div
- Game state display (location name, recent context)
- No framework (React, Vue, etc.) — this is a test harness, not a product UI

**Rationale**: Cannot evaluate "is this fun?" via curl or Postman. The minimal client validates the core hypothesis.

### 6.6 — Input Understanding: LLM or Rules?

**Decision: Rules first, LLM fallback for ambiguous input (option 3).**

- Pattern matching handles common inputs: movement ("go north"), examination ("look at X"), system commands ("save", "help")
- For everything else, call the `classification` model role to extract intent + entities
- This keeps latency low and costs down for simple inputs while handling the long tail

### 6.7 — Measuring Fun

**Decision: Structured playtesting with a `make playtest` command.**

The playtest harness:
1. Starts a game session
2. Records the full transcript (input + output + metadata)
3. After the session, prompts for ratings (1-5 on: fun, coherence, agency, surprise)
4. Saves transcript + ratings to `playtests/` directory

This is not automated — fun is a human judgment. But the infrastructure to capture feedback must be built alongside the game, not after.

---

## 7. Development Workflow

### 7.1 — Local Development

```bash
# Start infrastructure
make docker-up          # docker compose up -d (Postgres + Neo4j + Redis)

# Run the app (hot reload)
make dev                # uv run uvicorn tta.api.app:create_app --reload --factory

# Run tests
make test               # uv run pytest
make test-unit          # uv run pytest tests/unit/
make test-integration   # uv run pytest tests/integration/ -m integration
make test-bdd           # uv run pytest tests/bdd/

# Quality checks
make lint               # uv run ruff check src/ tests/ --fix && uv run ruff format src/ tests/
make typecheck          # uv run pyright src/
make check              # lint + typecheck + test (full CI gate)

# Playtesting
make playtest           # Start interactive session with transcript recording
```

### 7.2 — CI Pipeline (GitHub Actions)

```yaml
# Triggered on: push to main, PR to main
jobs:
  quality:
    steps:
      - ruff check (lint)
      - ruff format --check (formatting)
      - pyright (type check)
  test:
    services: [postgres, neo4j, redis]
    steps:
      - pytest tests/unit/
      - pytest tests/integration/ -m integration
      - pytest tests/bdd/
      - coverage report (fail < 80% on game-critical)
  build:
    steps:
      - docker build
      - docker compose config --quiet (validate compose file)
```

### 7.3 — Branching Strategy

- `main` is always deployable. CI gate prevents broken merges.
- Feature branches: `feat/description`, `fix/description`
- PRs required for all changes. At least one review (human or AI).
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- No direct push to `main`.

### 7.4 — Configuration

All configuration via environment variables. Loaded by Pydantic Settings.

```python
class Settings(BaseSettings):
    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]

    # Databases
    postgres_url: str = "postgresql+asyncpg://tta:tta@localhost:5432/tta"
    postgres_url_sync: str = "postgresql+psycopg://tta:tta@localhost:5432/tta"  # For Alembic CLI
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str  # No default — must be set
    redis_url: str = "redis://localhost:6379/0"

    # LLM
    llm_primary_model: str = "claude-sonnet-4-20250514"
    llm_fallback_model: str = "claude-haiku-4-20250514"
    llm_classification_model: str = "claude-haiku-4-20250514"
    llm_api_key: str  # No default — must be set

    # Observability
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3001"  # Self-hosted default; override for cloud
    log_level: str = "INFO"

    # Game
    max_input_length: int = 2000
    turn_rate_limit: int = 10  # per minute per session
    session_ttl_seconds: int = 3600

    model_config = SettingsConfigDict(env_file=".env", env_prefix="TTA_")
```

---

## 8. Docker Compose (v1)

```yaml
services:
  tta-api:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    depends_on:
      tta-postgres:
        condition: service_healthy
      tta-neo4j:
        condition: service_healthy
      tta-redis:
        condition: service_healthy

  tta-postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: tta
      POSTGRES_PASSWORD: tta
      POSTGRES_DB: tta
    volumes: ["pg-data:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tta"]
      interval: 5s
      retries: 5

  tta-neo4j:
    image: neo4j:5-community
    environment:
      NEO4J_AUTH: neo4j/password
      NEO4J_PLUGINS: '["apoc"]'
    volumes: ["neo4j-data:/data"]
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 10s
      retries: 5

  tta-redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 5

  tta-langfuse:
    image: langfuse/langfuse:4
    profiles: ["langfuse"]
    ports: ["3001:3000"]
    environment:
      DATABASE_URL: "postgresql://tta:tta@langfuse-postgres:5432/langfuse"
      CLICKHOUSE_URL: "http://langfuse-clickhouse:8123"
      CLICKHOUSE_MIGRATION_URL: "clickhouse://langfuse-clickhouse:9000"
      REDIS_HOST: "langfuse-redis"
      REDIS_PORT: "6379"
      LANGFUSE_S3_EVENT_UPLOAD_BUCKET: "langfuse"
      LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT: "http://langfuse-minio:9000"
      LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID: "minioadmin"
      LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY: "minioadmin"
      LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE: "true"
      LANGFUSE_S3_EVENT_UPLOAD_REGION: "us-east-1"
      NEXTAUTH_SECRET: "dev-secret-change-in-prod"
      NEXTAUTH_URL: "http://localhost:3001"
      SALT: "dev-salt-change-in-prod"
    depends_on:
      langfuse-postgres:
        condition: service_healthy
      langfuse-clickhouse:
        condition: service_started
      langfuse-redis:
        condition: service_started
      langfuse-minio:
        condition: service_started

  langfuse-worker:
    image: langfuse/langfuse-worker:4
    profiles: ["langfuse"]
    environment:
      DATABASE_URL: "postgresql://tta:tta@langfuse-postgres:5432/langfuse"
      CLICKHOUSE_URL: "http://langfuse-clickhouse:8123"
      CLICKHOUSE_MIGRATION_URL: "clickhouse://langfuse-clickhouse:9000"
      REDIS_HOST: "langfuse-redis"
      REDIS_PORT: "6379"
      LANGFUSE_S3_EVENT_UPLOAD_BUCKET: "langfuse"
      LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT: "http://langfuse-minio:9000"
      LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID: "minioadmin"
      LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY: "minioadmin"
      LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE: "true"
      LANGFUSE_S3_EVENT_UPLOAD_REGION: "us-east-1"
    depends_on:
      langfuse-postgres:
        condition: service_healthy

  langfuse-postgres:
    image: postgres:16-alpine
    profiles: ["langfuse"]
    environment:
      POSTGRES_USER: tta
      POSTGRES_PASSWORD: tta
      POSTGRES_DB: langfuse
    volumes:
      - langfuse-pg-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tta"]
      interval: 5s
      retries: 5

  langfuse-clickhouse:
    image: clickhouse/clickhouse-server:latest
    profiles: ["langfuse"]
    volumes:
      - langfuse-ch-data:/var/lib/clickhouse

  langfuse-redis:
    image: redis:7-alpine
    profiles: ["langfuse"]

  langfuse-minio:
    image: minio/minio:latest
    profiles: ["langfuse"]
    command: server /data --console-address ":9090"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - langfuse-minio-data:/data
    # Note: Bucket "langfuse" must be created on first run.
    # Use `mc mb local/langfuse` or the MinIO console at :9090.

volumes:
  pg-data:
  neo4j-data:
  langfuse-pg-data:
  langfuse-ch-data:
  langfuse-minio-data:
```

**Usage:**
```bash
docker compose up                         # Core services only (fast dev start)
docker compose --profile langfuse up      # Core + full Langfuse stack
```

The TTA app handles Langfuse being unreachable gracefully (§5.3) — tracing is skipped,
gameplay continues normally.

---

## 9. Implementation Wave Strategy

Waves define the build order. Each wave produces independently testable deliverables.

| Wave | Focus | Key Deliverables | Depends On |
|------|-------|-----------------|------------|
| **0** | Contracts | Pydantic models, interface protocols, safety hook protocol | Specs |
| **1** | Bootstrap | pyproject.toml, Docker Compose, CI, project skeleton, health endpoint | Wave 0 |
| **2** | LLM + Pipeline | LiteLLM wrapper, 4 pipeline stages, pipeline orchestrator | Wave 1 |
| **3** | World + Genesis | Neo4j schema, world queries, Genesis-lite, world templates | Wave 1 |
| **4** | API + Sessions | REST endpoints, SSE streaming, session management, web client | Waves 2+3 |
| **5** | Integration | End-to-end playtest, prompt tuning, BDD tests, error hardening | Wave 4 |

Component plans (`plans/llm-and-pipeline.md`, etc.) detail each wave's internals.

---

## 10. Open Items for Component Plans

The following details are NOT resolved here — they belong in component-level plans:

| Question | Resolved in |
|----------|-------------|
| Additional Pydantic model fields beyond TurnState core (§4.3 is normative) | `plans/llm-and-pipeline.md` |
| Neo4j Cypher query patterns for context assembly | `plans/world-and-genesis.md` |
| FastAPI dependency injection wiring | `plans/api-and-sessions.md` |
| Prompt template format and registry design | `plans/prompts.md` |
| CI job matrix and test markers | `plans/ops.md` |
| World template JSON schema | `plans/world-and-genesis.md` |
| Genesis-lite prompt sequence | `plans/world-and-genesis.md` |
| Supplementary SQLModel tables beyond core schema (§3.2 is normative) | `plans/api-and-sessions.md` |
| S11 full auth (email/password, OAuth, refresh tokens) | Post-MVP. Seams exist in `players` + `player_sessions` tables. |
