# NEXT_STEPS — TTA Rebuild Strategic Plan

> **Created**: 2025-07-25
> **Phase**: SDD Phase 2 (Plan) — preparing for Phase 3 (Tasks)
> **Input**: 23 specs (S00–S22), project charter, OSS research
> **Status**: Strategic recommendations — not yet a technical plan

---

## 1. OSS Stack Assessment

### LiteLLM — LLM Gateway

**What it does**: Unified Python SDK for 100+ LLM providers. Handles model
routing, streaming, automatic fallback, cost tracking, and budget limits.

**Fitness for TTA**: ✅ **Strong fit**. Maps directly to S07's requirements:
model roles, 2-3 tier fallback, streaming, per-turn cost tracking.

**Recommendation**: Use as a **library** (`litellm.completion()`), not as the
proxy server. The proxy adds a container, a network hop, and operational
complexity we don't need at v1 scale. If we later need multi-team API key
management, promote to proxy.

**Risks**:
- Large dependency tree (pulls in many provider SDKs)
- Rapid release cadence — pin versions aggressively
- Cost tracking accuracy varies by provider
- Fallback across model families can change narrative tone mid-session (see §7)

**Alternatives considered**: Direct OpenAI SDK (too coupled), custom wrapper
(violates "Not Our Code" fence).

---

### LangGraph — Workflow Orchestration

**What it does**: Graph-based state machine framework for multi-step AI
workflows. Supports conditional branching, checkpointing, and shared typed
state.

**Fitness for TTA**: ⚠️ **Conditional fit**. S08's turn pipeline is a mostly
linear 4-stage flow (Input Understanding → Context Assembly → Generation →
Delivery). LangGraph excels at cyclic, branching, resumable workflows —
capabilities we don't need in v1.

**Recommendation**: **Start without it.** Build the pipeline as a plain Python
async orchestrator with typed state (Pydantic models). The stages are well-
defined with clear contracts (S08 §7). If we later need resumable workflows,
human-in-the-loop, or complex branching recovery, adopt LangGraph then.

**Why not adopt immediately?**
- Adds abstraction before it adds value for a linear pipeline
- Steep learning curve for contributors
- Checkpointing and durable execution are overkill for synchronous turn
  processing
- We can always wrap our orchestrator in LangGraph later without rewriting
  business logic

**If we do adopt**: Use it ONLY for the turn pipeline graph. Do not make every
function call a LangGraph node.

---

### Langfuse — LLM Observability & Prompt Management

**What it does**: Open-source tracing, prompt versioning, cost tracking, and
evaluation platform for LLM applications. Self-hostable via Docker.

**Fitness for TTA**: ✅ **Strong fit**. Maps to S07 (trace every LLM call),
S09 (prompt versioning), and S15 (observability).

**Recommendation**: Use Langfuse **cloud free tier** for development and early
testing. Self-host for staging/production. The cloud tier avoids adding a
container to the dev docker-compose stack early on.

**Risks**:
- Self-hosted Langfuse needs 4 CPU / 16GB RAM — heavier than TTA itself
- Cloud tier sends prompts and completions to Langfuse servers. For a game
  with therapeutic future ambitions, audit what text gets logged.
- Adds PostgreSQL dependency (Langfuse's own DB) — don't confuse with TTA's
  PostgreSQL

**Alternatives considered**: LangSmith (not OSS), custom OTEL (too much work),
no observability (negligent for an LLM app).

---

### FastAPI — API Framework

**What it does**: Async Python web framework with automatic OpenAPI docs,
dependency injection, and native SSE support.

**Fitness for TTA**: ✅ **No-brainer**. The spec (S10) already mandates it.
SSE via `StreamingResponse`, async/await throughout, Pydantic models for
request/response validation.

**Risks**: None meaningful. Well-maintained, huge ecosystem, team familiarity.

---

### Neo4j Community Edition — World Graph Database

**What it does**: Native graph database. Cypher query language. ACID
transactions. Schema-optional nodes and relationships.

**Fitness for TTA**: ✅ **Good fit for v1**. World data IS graph-shaped (S04,
S13). Traversal queries ("what's adjacent?", "what does this NPC know?") are
native operations.

**Community Edition limitations**:
- No clustering/HA — single instance only
- Cold backups only (must stop DB to back up)
- No RBAC — single user
- Slower Cypher runtime than Enterprise (no parallel queries)
- No multiple databases per instance

**Why CE is fine for v1**: We target hundreds of concurrent players on a single
host (S14). Single-instance is the deployment model. No RBAC needed because
Neo4j is not exposed externally. Cold backups are acceptable for a game, not a
bank.

**Migration path**: If we outgrow CE, AuraDB (managed Neo4j) is the escape
hatch. Don't build around Enterprise-only features.

**Alternatives considered**: PostgreSQL with ltree/jsonb (possible but awkward
for deep traversals), FalkorDB (Redis-based graph, interesting but immature),
in-memory graph (doesn't persist).

---

### Redis — Session Cache & Messaging

**What it does**: In-memory data store. Key-value, pub/sub, streams.

**Fitness for TTA**: ✅ **Standard**. Session cache (S11), SSE event
distribution (S10), and potentially background task coordination.

**Anti-pattern to avoid**: Do NOT treat Redis as durable storage. All critical
state must be persisted to PostgreSQL or Neo4j. Redis is ephemeral — it may be
flushed or restarted.

---

### PostgreSQL — Relational Data

**What it does**: Production relational database.

**Fitness for TTA**: ✅ **Right tool for player data**. Player profiles,
session metadata, turn transcripts, audit logs, system configuration.

**Recommendation**: Use PostgreSQL from day one — including in development. Do
NOT use SQLite-in-dev / Postgres-in-prod. This creates migration drift and
hides bugs. Docker makes Postgres trivially available locally.

**ORM**: SQLModel (or raw asyncpg for performance-critical paths). Keep the
abstraction thin.

---

### pytest-bdd — BDD Test Execution

**What it does**: pytest plugin that executes Gherkin feature files within the
pytest ecosystem.

**Fitness for TTA**: ✅ **Better fit than Behave** for this project. The spec
(S16) mandates pytest. pytest-bdd integrates with pytest fixtures, pytest-xdist
(parallel execution), and existing test infrastructure.

**Trade-off**: Behave has more complete Gherkin support (data tables, scenario
outlines). pytest-bdd's subset is sufficient for TTA's acceptance criteria,
and the ecosystem integration wins.

**Risk**: 320 acceptance criteria across 23 specs is a LOT of BDD tests. Be
disciplined about which ACs become automated BDD tests vs. which are validated
by unit/integration tests. BDD tests are for user-visible behavior, not
internal implementation details.

---

## 2. The Ink Question

### Should TTA use Ink (or similar) for story structure?

**Recommendation: No Ink for v1. But not pure freeform LLM either.**

### Why not Ink?

1. **TTA's core differentiator is emergent narrative.** Every playthrough
   generates a unique world (Genesis, S02). Ink is designed for pre-authored
   branching stories. TTA is not a choose-your-own-adventure — it's a
   simulated world that responds to free-text input.

2. **Ink adds authoring complexity.** You'd need story writers, an Ink
   authoring pipeline, Python bindings (via `bink`), and a runtime that
   mediates between scripted structure and LLM generation. That's a project
   within a project.

3. **The world graph IS the structure.** Neo4j's world graph (S13) provides
   the constraints that Ink would provide in a traditional IF game: what
   exists, where it is, what's possible. The LLM writes prose within those
   constraints — it doesn't improvise in a vacuum.

4. **Hybrid can come later.** If narrative quality proves insufficient with
   pure LLM generation, Ink-authored story beats can be layered in as a
   future enhancement. The architecture doesn't foreclose this.

### But don't skip structure entirely

The biggest risk of pure-LLM generation is **coherence drift and
untestability**. Without structure, the LLM will:
- Contradict earlier world facts
- Shift tone unpredictably (especially on model fallback)
- Produce narrative that "sounds good" but breaks game rules
- Be impossible to regression-test

**Structural guardrails to build instead of Ink:**

| Guardrail | Purpose |
|-----------|---------|
| **World fact constraints** | LLM generation prompt includes current world state as ground truth |
| **Scene/beat tracker** | Track narrative pacing (tension, release, exploration) to guide generation |
| **Per-turn state diffs** | After each turn, extract and record what changed in the world |
| **Transcript regression harness** | Replay recorded sessions to detect quality regressions |
| **Prompt versioning** | Every turn records the exact prompt version used, enabling replay |

### Twine/Twee?

**Not relevant for v1.** Twine is an authoring tool for branching hypertext
narratives. TTA doesn't have authored branches — it has a world simulation.
Twine's export formats (Twee, HTML) don't map to TTA's architecture. If TTA
ever supports exported story playback (S20), Twine format might be an export
target, not an input format.

---

## 3. MVP Scope

### The Minimum Playable Slice

The goal is not "build the platform." The goal is: **one player, one session,
types text, gets streamed narrative that remembers what happened.**

#### In MVP

| Spec | What's included | What's deferred within spec |
|------|-----------------|---------------------------|
| **S01** (Gameplay Loop) | Core turn cycle, turn types (action/speak/explore), session save/resume | Chapter system, session recap, meta-progression, replayability |
| **S02** (Genesis) | **Lite version**: 2-3 guided prompts that seed a world template. NOT the full 5-act narrative experience. | Full narrative Genesis, act structure, character emergence |
| **S03** (Narrative Engine) | Second-person narrator, genre-aware tone, streaming delivery | Pacing system, callbacks/foreshadowing, beat tracking |
| **S07** (LLM Integration) | Model roles, 2-tier fallback (primary + fallback), streaming | Circuit breaking, cost dashboards, 3rd-tier last-resort |
| **S08** (Turn Pipeline) | All 4 stages (understand → context → generate → deliver) | Full entity resolution, emotional tone adaptation |
| **S10** (API & Streaming) | POST /turns, GET /games, SSE streaming, health endpoint | API versioning, rate limiting, admin endpoints, reconnection |
| **S12** (Persistence) | Postgres for turns/sessions, Neo4j for world, Redis for active session | Full migration strategy, backup automation |
| **S14** (Deployment) | docker-compose with api + neo4j + redis + postgres | Worker container, CI/CD, staging environment |
| **Web client** | Minimal HTML/JS page that submits turns and renders SSE | Not a real frontend. A test harness. |

#### Explicitly deferred (entire specs)

| Spec | Why deferred |
|------|-------------|
| S04 (World Model depth) | World graph seeds from Genesis-lite with a template; full dynamic world simulation is post-MVP |
| S05 (Choice & Consequence) | Meaningful consequences need a functioning world model first |
| S06 (Character System) | Emergent character growth needs many turns of gameplay data |
| S09 (Prompt Management) | Prompts are in code/config for MVP. Langfuse prompt UI is post-MVP |
| S11 (Player Identity) | MVP uses a session token, not full auth. One player, one browser. |
| S13 (World Graph depth) | Minimal schema for MVP: Location, NPC, Item, Connection. Not the full spec. |
| S15 (Observability) | Basic structured logging. Langfuse tracing. No dashboards. |
| S16 (Testing Infra) | CI pipeline. No golden tests, no LLM eval harness yet. |
| S17 (Data Privacy) | No PII beyond a player handle. Privacy seams exist but aren't enforced. |
| S18-S22 (Future) | Out of v1 fence per charter |

#### Why this scope?

**Validates the core hypothesis**: Can an LLM + world graph produce fun,
coherent interactive fiction? If the answer is yes with this thin slice,
everything else is scaling. If the answer is no, adding more specs won't
fix it.

---

## 4. SDD Phase 2: Technical Plan Outline

The Technical Plan is a separate document. Here's what it should cover:

### 4.1 Contracts & Schemas (Critical — do this first)

- **TurnState schema**: The typed data structure that flows through the
  pipeline. What fields exist at each stage? What's required vs. optional?
- **SSE event schema**: Event types (`narrative_token`, `turn_complete`,
  `error`, `keepalive`), payload shapes, reconnection protocol
- **World graph seed format**: What does Genesis-lite output? JSON? Cypher
  statements? A Python object?
- **Persistence ownership matrix**: Which entity lives where?

| Entity | Source of Truth | Cache | Retention |
|--------|----------------|-------|-----------|
| World graph (locations, NPCs, items) | Neo4j | — | Per-game lifetime |
| Player profile | PostgreSQL | — | Until deletion |
| Session metadata | PostgreSQL | Redis (active) | Per-game lifetime |
| Turn transcript | PostgreSQL | — | Per-game lifetime |
| Active game state | Redis | — | Ephemeral (rebuilt from DB on miss) |
| LLM traces | Langfuse | — | 90 days default |
| Prompt templates | Code/config | — | Versioned with deploys |

### 4.2 Pipeline Architecture

- The 4-stage pipeline as async Python functions with typed input/output
- How streaming works end-to-end (LLM → pipeline → SSE → client)
- Error handling at each stage
- Where LLM calls happen (stages 1 and 3, not 2 and 4)

### 4.3 Safety Seams

Even though full safety systems are deferred, the architecture must include:
- **Pre-generation hook**: Inspects parsed input before it reaches the LLM
- **Post-generation hook**: Inspects LLM output before it reaches the player
- **Stream interruption**: Ability to halt SSE mid-stream if post-gen hook
  flags content
- **Audit log**: Append-only record of every turn (input + output + metadata)

These are interfaces now, implementations later. But if we don't design the
seams, we'll rewrite the pipeline when safety becomes a requirement.

### 4.4 Project Structure

```
src/
  tta/
    api/           # FastAPI routes, SSE streaming
    pipeline/      # Turn processing stages
    llm/           # LiteLLM wrapper, model roles, fallback
    world/         # Neo4j graph operations, world queries
    genesis/       # World/character seeding
    models/        # Pydantic schemas (TurnState, GameState, etc.)
    persistence/   # PostgreSQL repos, Redis session management
    safety/        # Hook interfaces (pre/post generation)
tests/
  unit/
  integration/
  bdd/             # pytest-bdd feature files
```

### 4.5 Configuration & Environment

- All config via environment variables + `.env` file
- Model role → provider/model mapping in YAML/TOML config
- No secrets in code, ever

### 4.6 Development Workflow

- Local: `docker compose up` for infra, `uv run` for app (hot reload)
- CI: lint → type-check → unit tests → integration tests → build
- Branching: feature branches, PR-based merges, no direct push to main

---

## 5. SDD Phase 3: Task Decomposition Strategy

### Principles

1. **Each task is one PR.** If a task needs multiple PRs, it's too big.
2. **Each task has acceptance criteria** traced to a spec AC.
3. **Each task is independently testable.** No "this works once the next
   task is done."
4. **Vertical over horizontal.** Prefer "turn submission works end-to-end
   (thin)" over "all persistence is done (wide)."

### Suggested Wave Structure

#### Wave 0: Contracts (1 week)
Before any code, define the contracts that all subsequent work depends on.

| Task | Deliverable |
|------|-------------|
| Define TurnState schema | Pydantic models for each pipeline stage I/O |
| Define SSE event schema | Event type enum, payload models |
| Define world seed format | Genesis-lite output → Neo4j input contract |
| Define persistence matrix | Entity → DB mapping (as table in tech plan) |
| Define safety hook interfaces | Pre/post-generation callable protocols |

#### Wave 1: Repo Bootstrap (1 week)
Establish the project skeleton. No game logic yet.

| Task | Deliverable |
|------|-------------|
| Create pyproject.toml | Python 3.12+, uv, ruff, pyright, pytest |
| Create docker-compose.yml | api + neo4j + redis + postgres containers |
| Create project structure | `src/tta/` package skeleton with `__init__.py` files |
| Set up CI pipeline | GitHub Actions: lint, type-check, test, build |
| Create .env.example | All required env vars with safe defaults |
| Create Makefile | `make dev`, `make test`, `make lint`, `make docker-up` |
| Create minimal FastAPI app | Health endpoint, CORS, error handlers |

#### Wave 2: LLM Layer + Pipeline Skeleton (1-2 weeks)
Get LLM calls working with streaming and fallback.

| Task | Deliverable |
|------|-------------|
| LLM wrapper with LiteLLM | Model roles, streaming, 2-tier fallback |
| Input Understanding stage | Intent classification (can be rule-based for MVP) |
| Context Assembly stage | Query Neo4j for location context, recent history |
| Generation stage | Prompt construction, LLM call, streaming output |
| Delivery stage | SSE event formatting, stream to client |
| Pipeline orchestrator | Wire 4 stages together, typed state threading |

#### Wave 3: World & Genesis (1-2 weeks)
Give the pipeline something to talk about.

| Task | Deliverable |
|------|-------------|
| Neo4j schema (minimal) | Location, NPC, Item nodes + relationships |
| World seed loader | Load a world template into Neo4j |
| Genesis-lite flow | 2-3 prompts → world seed → load into graph |
| World query layer | Get location context, get nearby NPCs, get inventory |

#### Wave 4: API & Sessions (1 week)
Make it playable from a browser.

| Task | Deliverable |
|------|-------------|
| POST /games (create game) | Creates session, runs Genesis-lite |
| POST /games/{id}/turns | Submits turn, triggers pipeline, returns SSE stream |
| GET /games/{id} | Returns current game state |
| Session management | Redis-backed active session, Postgres persistence |
| Minimal web client | HTML page with input box and SSE reader |

#### Wave 5: Characters & World Depth (Issues #29-#34)
Deepen NPC characterization, relationship tracking, and world graph fidelity.

| Task | Issue | Status | Deliverable |
|------|-------|--------|-------------|
| Neo4j schema verification & extension | #29 | ✅ Done (PR #47) | S13 relationship coverage, migration 001 |
| Wire `get_recent_events()` to PostgreSQL | #33 | ✅ Done (PR #47) | Event persistence layer |
| NPC model with tiers & personality | #30 | ✅ Done (PR #48) | NPCTier enum, 12 NPC fields, relationship models |
| Relationship tracking (5 dimensions) | #31 | ✅ Done (PR #48) | RelationshipService protocol + implementations |
| NPC dialogue context in generation | #32 | ✅ Done (PR #48) | `dialogue.py`, pipeline context integration |
| Genesis NPC seeding | #34 | ✅ Done (PR #48) | TemplateRelationship, enriched NPC creation |

**Delivered**: 755 tests, 88% coverage. New services: RelationshipService,
dialogue context builder. New models: NPCTier, RelationshipDimensions,
NPCRelationship, NPCDialogueContext, TemplateRelationship.

#### Wave 6: Choice & Consequences (Issues #35-#40)
Build the choice-consequence pipeline that makes player decisions meaningful.

| Task | Issue | Status | Deliverable |
|------|-------|--------|-------------|
| Choice classification (6 types) | #35 | ✅ Done (PR #49) | ChoiceType enum, rules-first classifier + LLM fallback |
| Consequence chain model | #36 | ✅ Done (PR #49) | ConsequenceChain/Entry with branching, 30-chain cap |
| World mutation pipeline | #37 | ✅ Done (PR #49) | ConsequenceService protocol + InMemory, evaluate/prune |
| Consequence injection in context | #38 | ✅ Done (PR #49) | `_enrich_consequences()` in context stage |
| Narrative anchor & divergence | #39 | ✅ Done (PR #49) | NarrativeAnchor, DivergenceScore, anchor service |
| Hidden consequence foreshadowing | #40 | ✅ Done (PR #49) | Hidden entry tracking, foreshadowing hints, reveal |

**Delivered**: 853 tests (98 new), 0 pyright errors. New packages:
`tta.choices` (classifier, consequence_service). New models: ChoiceType,
ImpactLevel, Reversibility, ChoiceClassification, ConsequenceEntry,
ConsequenceChain, NarrativeAnchor, DivergenceScore. Pipeline integration:
choice classification in understand stage, consequence injection in context
stage. Both non-blocking with graceful degradation.

#### Wave 7: Observability (Issues #41-#46)
Production-ready observability, testing, and privacy.

| Task | Issue | Status | Deliverable |
|------|-------|--------|-------------|
| Structured logging with correlation IDs | #42 | ✅ Done (PR #50) | structlog JSON + contextvars correlation_id, X-Trace-Id propagation |
| Prometheus metrics endpoint | #43 | ✅ Done (PR #50) | 15 metrics, `/metrics` endpoint, PrometheusMiddleware |
| Langfuse v4 integration | #41 | ✅ Done (PR #50) | PII-sanitized traces, session hierarchy, graceful degradation |
| OpenTelemetry distributed tracing | #44 | ✅ Done (PR #50) | Span hierarchy HTTP→pipeline→stage→llm_call, Jaeger export |
| BDD feature files for core gameplay | #45 | ✅ Done (PR #50) | 3 feature files (11 BDD tests), 20 Hypothesis property tests |
| Privacy-aware logging & cost tracking | #46 | ✅ Done (PR #50) | 4-tier data classification, 7 retention policies, cost tracker, GDPR stubs |

**Delivered**: 999 tests (146 new), 0 pyright errors. New packages:
`tta.observability` (metrics, tracing, langfuse), `tta.privacy`
(classification, retention, cost). Architecture: three separate observability
flows (logs/metrics/traces) unified by correlation_id. Prometheus metrics with
low-cardinality labels. OTel span hierarchy with Jaeger export. Langfuse with
pseudonymized player IDs. Data classification matrix (22 fields, 4 tiers).
Retention policies for 7 storage categories. LLM cost tracking with daily
alerting. BDD scenarios via pytest-bdd, Hypothesis property tests with profiles.

### Ordering Rationale

- **Wave 0 before everything**: Contracts prevent rework. If TurnState
  changes shape after Wave 2, you rewrite Wave 2.
- **Wave 2 before Wave 3**: You can test the pipeline with a hardcoded world
  context before Neo4j is integrated.
- **Wave 4 after Wave 3**: The API needs something real to serve.
- **Wave 5 deepens character models**: NPC tiers, relationship dimensions,
  and dialogue context give the narrative engine material to differentiate
  characters. These models feed directly into Wave 6's consequence system.
- **Wave 6 makes choices matter**: The consequence pipeline turns player
  decisions into durable world state changes — the core value proposition.
- **Wave 7 is production readiness**: Observability, testing, and privacy
  are not blockers for gameplay but essential before any external players.

---

## 6. Repo Bootstrap Checklist

### Files that must exist before Wave 1 is "done"

```
fictional-barnacle/
├── .github/
│   └── workflows/
│       └── ci.yml              # Lint, type-check, test, build
├── src/
│   └── tta/
│       ├── __init__.py
│       ├── api/
│       │   ├── __init__.py
│       │   └── app.py          # FastAPI application factory
│       ├── pipeline/
│       │   └── __init__.py
│       ├── llm/
│       │   └── __init__.py
│       ├── world/
│       │   └── __init__.py
│       ├── genesis/
│       │   └── __init__.py
│       ├── models/
│       │   └── __init__.py
│       ├── persistence/
│       │   └── __init__.py
│       └── safety/
│           └── __init__.py
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   └── __init__.py
│   ├── integration/
│   │   └── __init__.py
│   └── bdd/
│       └── __init__.py
├── specs/                      # Already exists (23 specs)
├── docker-compose.yml
├── docker-compose.override.yml # Dev overrides (hot reload, debug)
├── Dockerfile
├── .env.example
├── pyproject.toml
├── Makefile
├── README.md
├── .gitignore
├── .python-version             # 3.12
└── ruff.toml                   # or [tool.ruff] in pyproject.toml
```

### pyproject.toml key decisions

```toml
[project]
name = "tta"
requires-python = ">=3.12"

[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "C4", "UP"]

[tool.pyright]
typeCheckingMode = "standard"
pythonVersion = "3.12"

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "integration: requires external services",
    "bdd: Gherkin acceptance tests",
]
```

### Core dependencies (v1)

```
# Runtime
fastapi
uvicorn[standard]
litellm
neo4j                # async driver
asyncpg              # or sqlmodel + asyncpg
redis[hiredis]
pydantic>=2
pydantic-settings
tenacity
httpx                # for testing + internal HTTP

# Observability
langfuse
structlog

# Dev/Test
pytest
pytest-asyncio
pytest-bdd
pytest-cov
ruff
pyright
```

### Docker Compose services (v1)

| Service | Image | Purpose |
|---------|-------|---------|
| `tta-api` | Custom (Dockerfile) | FastAPI app |
| `tta-neo4j` | `neo4j:5-community` | World graph |
| `tta-redis` | `redis:7-alpine` | Session cache, pub/sub |
| `tta-postgres` | `postgres:16-alpine` | Player data, transcripts |

Note: **No worker container for MVP.** Turn processing happens in-process
(async). A background worker is a scaling optimization, not an MVP need.

Note: **No Langfuse container for MVP.** Use cloud free tier or run
separately. Don't bloat the dev docker-compose.

---

## 7. Open Architectural Questions

These must be answered before implementation starts. They are not optional.

### 7.1 Model Fallback and Narrative Consistency

**Question**: When the LLM falls back from a primary model (e.g., Claude) to a
fallback (e.g., GPT-4o-mini), how do we prevent jarring tone/quality shifts
mid-session?

**Options**:
1. Pin model per session (no fallback within a session — fail instead)
2. Fallback only within the same model family (Claude → Haiku, not Claude → GPT)
3. Accept the quality shift and rely on prompt engineering to normalize tone
4. Capability-gated fallback: only fallback for classification, never for generation

**Recommendation**: Option 2 (same-family fallback) as default, with option 4
as a refinement.

### 7.2 World Graph Seeding Strategy

**Question**: How does Genesis-lite create a world? Options:
1. **Template library**: Pre-defined world templates (forest village, space
   station, etc.) with randomized details
2. **LLM-generated seed**: LLM generates a world description → parser extracts
   entities → loader creates graph
3. **Hybrid**: Template skeleton + LLM fills in flavor, names, descriptions

**Recommendation**: Option 3. Templates provide structure (and testability);
LLM provides uniqueness. This is the pragmatic middle ground.

### 7.3 Turn Transcript Format

**Question**: How are turn transcripts stored? Options:
1. Raw text (player input + LLM output as strings)
2. Structured JSON (parsed intent, entities, world state diff, raw text)
3. Both (structured for querying, raw for replay)

**Recommendation**: Option 3. Structured data enables the regression harness
and debugging. Raw text enables faithful replay.

### 7.4 SSE Reconnection Contract

**Question**: If a player disconnects mid-stream, what happens when they
reconnect?

**Options**:
1. Replay the full response from the beginning
2. Resume from the last acknowledged event (requires client-side tracking)
3. Skip to the completed state (show the final narrative block, not streamed)

**Recommendation**: Option 3 for MVP. Reconnection shows the completed turn.
Full SSE reconnection with `Last-Event-ID` is a post-MVP optimization.

### 7.5 Frontend for v1

**Question**: API-only, or ship a minimal client?

**Recommendation**: **Ship a minimal web client.** Not a React app — a single
HTML file with vanilla JS that submits turns and renders SSE. This validates
the two most important things: **fun** and **stream UX**. You cannot evaluate
"is this game fun?" via curl.

### 7.6 Input Understanding: LLM or Rules?

**Question**: Should Stage 1 (Input Understanding) use an LLM call, or
rule-based parsing?

**Options**:
1. Always LLM (classification role, structured JSON output)
2. Always rules (regex + keyword matching)
3. Rules first, LLM fallback for ambiguous input

**Recommendation**: Option 3. Rules are fast, cheap, and testable. LLM handles
the long tail of ambiguous input. This keeps latency low and costs down for
simple inputs like "look around" or "go north."

### 7.7 Evaluation: How Do We Know If It's Fun?

**Question**: How do we measure the core success metric — "is this fun?" —
during development?

**This has no automated answer.** The plan should include:
- Structured playtesting sessions (even solo)
- Turn-by-turn transcript review
- Likert-scale self-ratings after sessions
- Narrative coherence spot-checks
- A/B prompt variants with qualitative comparison

Build a `make playtest` command that starts a session, records the transcript,
and prompts for ratings at the end. This is the most important feedback loop
in the project.

---

## 8. Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|------------|
| LLM narrative drifts from world state | High | High | World fact injection in every prompt; state diff validation |
| Model fallback degrades quality mid-session | Medium | Medium | Same-family fallback; prompt normalization |
| Neo4j CE performance at scale | Low | Low | v1 scale is tiny; AuraDB is the escape hatch |
| Langfuse captures sensitive player text | Medium | Medium | Data classification rules; redaction before logging |
| LangGraph adds complexity without value | Medium | High (if adopted) | Don't adopt it for v1 |
| 23 specs create analysis paralysis | High | Medium | MVP fence is firm; defer ruthlessly |
| pytest-bdd can't handle all 320 ACs | Low | Low | Not all ACs need BDD tests; most are unit/integration |
| Pure-LLM narrative isn't "fun enough" | High | Medium | Prompt iteration; structural guardrails; Ink as future fallback |
| No frontend means untestable UX | High | High (if skipped) | Ship the minimal web client |

---

## 9. What This Document Is Not

- **Not a technical plan.** The technical plan (SDD Phase 2) will contain
  implementation-level decisions: exact schemas, API contracts, database
  migrations, prompt templates.
- **Not a task list.** The task breakdown (SDD Phase 3) will decompose specs
  into PRs with acceptance criteria, dependencies, and estimates.
- **Not permanent.** Revisit this document after Wave 0 contracts are defined
  and after the first playtest session. Both will invalidate assumptions.

---

## 10. Wave 8 — Vertical Integration (Complete ✅)

**Status**: All 6 issues complete. 1021 tests (12 integration), 0 pyright errors.

### Completed (PRs merged)

| PR | Issue | Summary |
|----|-------|---------|
| #57 | #53, #51 | Wire Neo4jWorldService (opt-in via `neo4j_uri`) + inject ConsequenceService into PipelineDeps |
| #58 | #54 | TurnResultStore protocol — InMemory + Redis implementations, SUBSCRIBE-before-GET pattern |
| #59 | #52 | `make playtest` CLI — interactive httpx-based script with SSE streaming, color output |
| — | #55 | Integration test suite: 12 tests across 5 classes exercising full turn cycle with real Postgres+Redis |
| — | #56 | Web playtest client: `static/playtest.html` with EventSource SSE streaming, cookie auth, dark theme |

### Key decisions

- **Neo4j opt-in**: `neo4j_uri` defaults to `""` (not `bolt://localhost:7687`). Set it to enable Neo4j; otherwise InMemoryWorldService is used. This avoids breaking unit tests that don't have Neo4j running.
- **TurnResultStore**: Protocol-based with InMemory (asyncio.Event) and Redis (pub/sub + TTL) backends. Keyed by `turn_id`, not `game_id`. No DELETE on read — TTL handles cleanup.
- **Playtest CLI**: Standalone `scripts/playtest.py`, reads `TTA_BASE_URL` env var, supports `--base-url` override. Decoupled from Docker orchestration.
- **JSONB encoding fix**: Discovered that `sa.type_coerce(value, sa.JSON)` doesn't work with `sa.text()` + asyncpg — replaced with `json.dumps(value)` in 3 places in postgres.py.
- **EventSource auth**: Browser EventSource can't send custom headers, but supports `withCredentials: true` for cookie-based auth. CORS `allow_credentials` was already enabled.
- **Podman compatibility**: `podman-compose` doesn't support `--wait` — replaced with `pg_isready` polling loop in Makefile.

---

## 11. Spec Gap Analysis — RESOLVED

A comprehensive review of S00–S22 identified 6 missing v1 specs and the S11/S17 data
deletion contradiction. **All gaps are now addressed:**

### Specs Written

| ID | Title | Plan | Lines |
|----|-------|------|------:|
| S23 | Error Handling & Resilience | `plans/resilience-and-safety.md` | ~430 |
| S24 | Content Moderation v1 | `plans/resilience-and-safety.md` | ~470 |
| S25 | Rate Limiting & Anti-Abuse | `plans/resilience-and-safety.md` | ~400 |
| S26 | Admin & Operator Tooling | `plans/ops.md` Part B | ~530 |
| S27 | Save/Load & Game Management | `plans/api-and-sessions.md` Part B | ~500 |
| S28 | Performance & Scaling | `plans/ops.md` Part C | ~500 |

### Plans Created / Extended

- **NEW**: `plans/resilience-and-safety.md` — covers S23, S24, S25 (663 lines)
- **EXTENDED**: `plans/ops.md` — Part B (S26 Admin Tooling), Part C (S28 Performance)
- **EXTENDED**: `plans/api-and-sessions.md` — Part B (S27 Save/Load)

### Contradiction Resolved

- **S11/S17 data deletion**: S17 FR-17.11 amended with tiered timeline — TTA-internal
  data erased within 72h (per S11 FR-11.62), third-party data (Langfuse) within 30 days.

### Remaining Overlaps to Track

| Area | Specs | Issue |
|------|-------|-------|
| Anonymous player lifecycle | S10, S11 | Neither owns conversion to permanent account |
| Session timeout semantics | S01, S11 | Unclear game state behavior on session expiry |
| LLM context ownership | S03, S08 | Both claim prompt assembly ownership |

### Coverage Assessment (Updated)

- **Well-covered (~90%)**: Core gameplay, world model, LLM integration, API contracts,
  persistence, observability, error handling, content moderation, rate limiting,
  performance targets, admin tooling, save/load UX
- **Partially covered (~5%)**: Security (S19 stub + S24 v1 minimum), player UX polish
- **Deferred (~5%)**: Therapeutic framework (S18), crisis safety (S19 full), sharing (S20),
  co-authoring (S21), community (S22)

---

## 12. Wave 9 — Resilience & Safety ✅

**Completed.** S23 (Error Handling & Resilience) + S25 (Rate Limiting & Anti-Abuse).
1147 tests, 0 pyright errors. HEAD 27b3329 on main.

Issues #60–#66, #76 (all closed):
- #60 Error taxonomy & envelope (S23)
- #61 Structured error logging & correlation (S23)
- #62 Retry utilities & circuit breaker (S23)
- #63 Health endpoint enhancement (S23)
- #64 Turn atomicity & SSE error events (S23)
- #65 Rate limiting core — sliding window & middleware (S25)
- #66 Anti-abuse detection with escalating cooldowns (S25)
- #76 Review comment fixes + BaseHTTPMiddleware → pure ASGI conversion

Key deliverables:
- 9-category error taxonomy with `correlation_id` envelope
- Circuit breaker (closed/open/half-open) with per-service config
- Health endpoint: healthy/degraded/unhealthy with subsystem checks
- Turn atomicity with concurrent turn rejection (409)
- SSE error events with standard envelope
- Sliding window rate limiter (Redis + in-memory fallback)
- Anti-abuse: rapid-fire + credential stuffing detection, escalating cooldowns
- All middleware converted from BaseHTTPMiddleware to pure ASGI (fixes SSE + asyncpg)

## 13. Wave 10 — Content Safety & Game Management ✅

**Completed.** S24 (Content Moderation v1) + S27 (Save/Load & Game Management) + PR #76 review debt.
1284 tests, 0 pyright errors. HEAD 376e371 on main.

Issues #78–#83 (all closed):
- #78 PR #76 review debt — X-RateLimit headers, PII stripping, stack trace sanitization (PR #84)
- #79 S24 content moderation core — models, keyword moderator, pipeline hooks (PR #85)
- #80 S24 stream interruption — moderation events, graceful degradation, health check (PR #87)
- #81 S24 flagging & audit trail — moderation_records table, auto-flag, structured logging (PR #88)
- #82 S27 game lifecycle — enhanced model, CRUD, cursor pagination, soft-delete (PR #86)
- #83 S27 auto-save & resume — auto-save hooks, context summary, title generation (PR #89)

Key deliverables:
- Content moderation module (`src/tta/moderation/`) with keyword-based v1 classifier
- ModerationVerdict (pass/flag/block) with 10 content categories
- Pipeline integration via SafetyHook protocol (understand + generate stages)
- SSE moderation events with stream interruption for blocked content
- Moderation records table with content hashes (no raw content in logs)
- Auto-flagging system: configurable threshold triggers session-level flags
- Game lifecycle state machine: ACTIVE → COMPLETED | ABANDONED
- Cursor-based game pagination, soft-delete with confirmation
- Auto-save hooks in turn pipeline (metadata in separate transaction)
- Resume endpoint with context summary, staleness checks, moderated turn inclusion
- Background title generation (genesis) and summary regeneration (every Nth turn)
- 3 Alembic migrations: 002 (game lifecycle), 003 (moderation_records), 004 (summary_generated_at)

## 14. Wave 11 — Admin & Performance ✅

**Completed.** S26 (Admin & Operator Tooling) + S28 (Performance & Scaling).
1303 tests, 0 pyright errors. PR #91 squash-merged to main (d855324).

Key deliverables:
- **S26 Admin API** — 16 endpoints at `/admin` prefix with token-based auth
  - Player management: list, search, get details, suspend, reinstate
  - Moderation queue: list flagged content, review (dismiss/warn/suspend_player)
  - Rate limit/abuse: reset player rate limit, unblock IP
  - Audit log: append-only with composite cursor pagination + date-range filtering
  - System health & Prometheus metrics exposure
  - Admin auth via `Authorization: Bearer <key>` matching `TTA_ADMIN_API_KEY` with timing-safe comparison (`secrets.compare_digest`)
- **S28 Performance controls**
  - LLM semaphore: bounded queue + timeout, Prometheus gauges, asyncio.Lock for race safety
  - DB connection pool tuning: pool_size, max_overflow, timeout, recycle, pre_ping
  - Latency budget middleware: pure ASGI, `asyncio.timeout()` for real request abort
  - 7 new Prometheus gauges for pool + semaphore observability
- **Migration 005**: player status/suspended_reason columns + audit_log table
- **Player enforcement**: `require_active_player` on create_game and submit_turn
- 20 new tests (12 admin, 5 semaphore, 3 latency middleware)
- All 16 Copilot code review comments addressed and resolved

## 15. Wave 12 — Observability Stack & Production Hardening

### Completed

- **Monitoring stack in Docker Compose** (Tier 1)
  - Prometheus v3.4.1 + Grafana OSS 11.6.0 as opt-in services (`--profile monitoring`)
  - Auto-provisioned Prometheus datasource and dashboard loader
  - Prometheus scrape config targeting tta-api:8000/metrics at 15s interval
  - Grafana on port 3001 (avoids Langfuse conflict on 3000)

- **Grafana dashboards** (S15 FR-15.26/27)
  - System Health: 9 panels — request rate, error rate, p50/p95/p99 latency, active sessions, in-flight requests, connection pools
  - Turn Pipeline: 6 panels — processing time by stage, LLM latency by model, token usage, safety flags, success/failure rate
  - Cost: 4 panels — LLM cost per hour/day, cost per model, cost per turn average

- **Prometheus alerting rules** (S15 FR-15.22/23)
  - 5 rules: API error rate >10%, LLM unreachable >2min, turn processing >30s p95, daily cost threshold, DB pool exhausted
  - LLMAPIUnreachable and DBPoolExhausted disabled until metrics are instrumented (Wave 13)
  - Prometheus rule evaluation only — Alertmanager for notification routing planned for future wave

- **Security headers middleware** (Tier 2)
  - Pure ASGI middleware: X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy, Permissions-Policy
  - CORS tightened: explicit method list (GET/POST/PUT/PATCH/DELETE/OPTIONS), explicit header allowlist
  - 6 unit tests covering header presence and CORS behavior

- **Documentation** (Tier 3)
  - README.md overhaul: quick-start guide, architecture diagram, port reference table, dev workflow
  - New `docs/deployment-runbook.md`: first deploy, monitoring access, backup/restore, troubleshooting, env vars reference

### Metrics

- Tests: 1315+ (6 new security header/CORS tests)
- Pyright: 0 errors
- Ruff: 0 errors

## 16. Wave 13 — Metrics Instrumentation & Compliance ✅

### Completed

- **Prometheus metrics instrumentation** (S15 FR-15.6/7/8/9, S28 FR-28.10/11)
  - LLM call metrics: TURN_LLM_CALLS, TURN_LLM_DURATION, TURN_LLM_TOKENS in litellm_client.py
  - Safety metrics: TURN_SAFETY_FLAGS in moderation hook.py
  - Session lifecycle: SESSIONS_ACTIVE, SESSION_TURNS, SESSION_DURATION in games.py
  - Re-enabled LLMAPIUnreachable alert (was disabled pending instrumentation)
  - Pool metrics (PG_POOL_SIZE, REDIS_POOL_ACTIVE, NEO4J_POOL_ACTIVE) deferred — need periodic sampling

- **Admin auth test coverage** (quality gap)
  - 7 test cases in tests/unit/admin/test_auth.py
  - Covers: no key configured, missing header, invalid token, valid token, timing-safe comparison, bearer prefix

- **Automated data purge job** (S17 FR-17.15)
  - New src/tta/privacy/purge.py: run_purge() (single pass, dry_run) + purge_loop() (24h background)
  - Deletes terminal sessions + associated turns older than retention policy (default 90 days)
  - Integrated into FastAPI lifespan (create_task on startup, cancel on shutdown)
  - Admin endpoint POST /admin/purge for manual trigger

- **SECURITY.md** (S17 FR-17.46–17.50)
  - Vulnerability reporting process with 48h acknowledgment SLA
  - Breach response plan with 72h notification timeline
  - Data categories and severity classification

- **Runtime log level endpoint** (S15 FR-15.4)
  - POST /admin/log-level with Pydantic validation
  - Changes structlog/stdlib root logger level at runtime
  - Audit-logged, returns previous and new level

- **X-Trace-Id response header** (S15 FR-15.16)
  - Always emits X-Trace-Id in responses (falls back to request_id when no trace ID provided)
  - Updated test to verify fallback behavior

### Metrics

- Tests: 1305 (7 new admin auth + 1 updated middleware test)
- Pyright: 0 errors
- Ruff: 0 errors

## 17. Wave 14 — Core Gameplay Integration (PR #TBD)

**Goal**: Make the game actually playable by wiring existing genesis and
world-change infrastructure into the game lifecycle.

### Critical Discovery

`run_genesis_lite()` (410 lines) and `apply_changes()` (173 lines) were **fully
implemented and tested but never called** from any game flow. `create_game()`
stored a flat JSON seed and returned — no world graph, no intro narrative, no
world state updates after turns.

### What Changed

- **TemplateRegistry initialization** — instantiated during app lifespan, stored
  on `app.state.template_registry`. New `select_by_preferences()` method scores
  templates without requiring a `WorldSeed` (resolved circular dependency).

- **Genesis wired into `create_game()`** — template selection (by `world_id` or
  preferences), `WorldSeed` construction, `run_genesis_lite()` call. Genesis
  result (world graph, intro narrative) stored in `world_seed` JSONB column.
  `narrative_intro` returned in `GameData` response.

- **World changes applied after turns** — `_dispatch_pipeline()` now translates
  LLM `world_state_updates` (list[dict]) to `WorldChange` models via
  `_translate_world_updates()` and calls `apply_changes()`.

- **Graceful degradation** — all genesis/world-change calls wrapped in try/except.
  If Neo4j is down or LLM fails, game creation and turns proceed without world
  enrichment. Log warnings, don't block gameplay.

- **`_ATTRIBUTE_TYPE_MAP`** — keyword-to-WorldChangeType mapping (15 keywords →
  9 change types). Sorted by descending key length to resolve substring conflicts
  (e.g., `"disposition"` before `"position"`, `"quest_status"` before `"status"`).

### Metrics

- Tests: 1342 (26 new genesis integration tests)
- Pyright: 0 errors
- Ruff: 0 errors

## 18. Wave 15 — Gameplay Loop Basics (PR #TBD)

> Branch: `wave-15/gameplay-loop-basics` from main at `a3564c9`

**Goal**: Make S01 Gameplay Loop actually playable — command system, empty-input
nudges, E2E smoke test, privacy policy, and pool metrics instrumentation.

### Key Changes

- **Command router** (S01 AC-1.10, AC-1.3) — `/help`, `/save`, `/status` return
  inline 200 JSON responses without creating DB turns or SSE streams. Unknown
  commands return help text. Commands bypass advisory lock and pipeline entirely.

- **Empty-input nudge** (S01 AC-1.2) — Blank/whitespace input returns a random
  in-world nudge phrase (10 phrases) instead of a 422 validation error. Relaxed
  `SubmitTurnRequest` to allow empty strings.

- **E2E gameplay smoke test** — 9 tests validating the full flow: create game →
  narrative turn → empty nudge → commands → turn history. Uses ASGI transport
  with mocked LLM/WorldService.

- **Privacy policy** (S17 FR-17.51-54) — `docs/privacy-policy.md` covering all
  10 required items in plain language. Served at `/privacy` as HTML. Version-
  controlled alongside code.

- **Pool metrics sampler** (S28) — Periodic sampler (30s) reads PG/Redis/Neo4j
  connection pool stats and sets Prometheus gauges. Wired into app lifespan.
  Graceful no-op when pools aren't initialized.

### Design Decision: Inline 200 for Commands/Nudges

Commands and nudges return HTTP 200 with inline JSON — no DB row, no SSE stream,
no turn_count pollution. Client distinguishes by status code: 202 = go to SSE,
200 = response inline. Validated by four independent rubber-duck critiques.

### Metrics

- Tests: 1378 (30 new: 12 command + 9 E2E + 4 privacy + 5 pool metrics)
- Pyright: 0 errors
- Ruff: 0 errors

## 19. Wave 16 — Character Commands & Session Lifecycle

**Branch**: `wave-16/character-commands-lifecycle`
**Specs**: S01, S06, S11, S12
**Tests**: 1404 passing (+26 over Wave 15 baseline of 1378)

### What shipped

1. **`/character` command** (S06-AC-6.1) — Displays player character name, concept,
   and tone from `world_seed` JSON. Graceful fallback for pre-genesis games.

2. **`/relationships` command** (S06-AC-6.3) — Shows template NPCs with roles and
   dispositions, loaded from `WorldTemplate.npcs` via `template_registry`.

3. **`/end` command** (S01-AC-1.6) — Transitions game from `active` → `ended`,
   returns epilogue-style message with prompt to start a new game.

4. **Lifecycle background job** (S11-AC-11.05-08) — New `src/tta/lifecycle/` module:
   - Rule 1: `active` + 0 turns + age > 24h → `abandoned`
   - Rule 2: `paused` + last_played > 30 days → `expired`
   - Runs every 1h alongside existing `purge_loop`

5. **GDPR account deletion** (S12-AC-12.03) — Replaced stub with real implementation:
   - Tombstones player: `status='pending_deletion'`, `handle='deleted-{id}'`
   - Ends all active/paused game sessions
   - NULLs PII: `turns.player_input`, `turns.narrative_output`,
     `game_sessions.world_seed`, `game_sessions.summary`
   - Deletes all `player_sessions` (session tokens)
   - Single transaction, immediate erasure (v1 simplicity)
   - Migration 006: adds `deletion_requested_at` to `players`

### Files added
- `src/tta/lifecycle/__init__.py`, `src/tta/lifecycle/cleanup.py`
- `tests/unit/lifecycle/__init__.py`, `tests/unit/lifecycle/test_cleanup.py`
- `migrations/postgres/versions/006_gdpr_deletion.py`

### Files modified
- `src/tta/api/routes/games.py` — 3 new commands + `deleted_at IS NULL` filter
- `src/tta/api/routes/players.py` — real GDPR deletion endpoint
- `src/tta/api/app.py` — lifecycle_loop wired into lifespan
- `src/tta/models/player.py` — `deletion_requested_at` field
- `tests/unit/api/test_commands.py` — 24 command tests (rewritten)
- `tests/unit/privacy/test_gdpr_endpoints.py` — 10 deletion tests (rewritten)

### Known v1 limitations
- `/character` shows static genesis data, not evolving traits (no live character state system)
- `/relationships` shows template NPCs, not live relationship state
- `/end` unreachable from paused games (submit_turn rejects non-active); use PATCH endpoint
- S11-AC-11.09/11.10 deferred (require email/password auth, not anonymous handles)

### AC coverage impact
- S06-AC-6.1 ✓, S06-AC-6.3 ✓, S01-AC-1.6 ✓
- S11-AC-11.06 ✓, S11-AC-11.08 ✓, S12-AC-12.03 ✓
- Estimated: ~35% → ~45% overall AC coverage

## 20. Wave 17 — Compliance, GDPR Multi-Store & Idle Timeout

**Branch**: `wave-17/compliance-gdpr-idle` | **PR**: #TBD | **Tests**: ~1415+

### Tasks Completed

1. **Purge timing fix** (FR-27.17): Added `soft_deleted_game_postgresql` retention policy
   with 3-day retention. Rewrote `purge.py` with dual cutoff paths — soft-deleted games
   purge at 72 hours, completed/expired sessions at 90 days.

2. **Multi-store GDPR erasure** (AC-12.03): Extended `request_account_deletion()` to clean
   Redis active sessions and Neo4j world graph data after PostgreSQL scrubbing. Graceful
   degradation — Redis/Neo4j failures don't block the deletion response.

3. **30-minute idle timeout** (AC-1.7): Added Rule 3 to lifecycle cleanup — active sessions
   with `turn_count > 0` and no activity for 30 minutes transition to `paused`. New games
   (0 turns) are excluded to preserve the 24h abandon window. Configurable via
   `idle_timeout_minutes` setting.

4. **Suggested actions** (AC-5.2): Extended LLM extraction prompt to request `suggested_actions`
   alongside `world_changes`. `_extract_world_changes()` now returns a tuple. Backwards
   compatible with plain list format from older LLM responses. Non-string and
   empty/whitespace-only suggestions are filtered; duplicates are deduplicated
   (case-insensitive) and fewer than 3 distinct suggestions discards the set.

5. **NEXT_STEPS.md update**: This section.

### AC Coverage Impact

| AC | Description | Status |
|----|-------------|--------|
| FR-27.17 | Soft-deleted data purged after 72 hours | ✅ Fixed |
| AC-12.03 | GDPR erasure from ALL data stores | ✅ Complete |
| AC-1.7 | 30-min idle → auto-save + pause | ✅ Implemented |
| AC-5.2 | Suggested actions populated per turn | ✅ Implemented |

Estimated AC coverage: ~45% → ~52%

### Key Files Changed

- `src/tta/privacy/retention.py` — new `soft_deleted_game_postgresql` policy
- `src/tta/privacy/purge.py` — dual cutoff purge rewrite
- `src/tta/api/routes/players.py` — multi-store GDPR cleanup
- `src/tta/lifecycle/cleanup.py` — idle timeout Rule 3
- `src/tta/pipeline/stages/generate.py` — suggested actions extraction
- `src/tta/config.py` — `idle_timeout_minutes` setting
- `src/tta/api/app.py` — call signature fixes
- `src/tta/api/routes/games.py` — suggested_actions SSE wiring

## 21. Wave 18 — Observability Hardening, Input Validation, Resume Recap

**Branch**: `wave-18/observability-validation-recap`
**Tests**: 1441 total (26 new), 0 pyright errors

### Completed

1. **Rate limit & abuse metrics** (S15 C1): Added `tta_rate_limit_enforced_total`
   counter (labels: route) in rate limit middleware, and `tta_abuse_detected_total`
   counter (labels: pattern) in both InMemory and Redis abuse detectors.

2. **DB query duration & Redis metrics** (S15 §4 C4): Added
   `tta_db_query_duration_seconds` histogram (labels: database, operation) and
   `tta_redis_operations_total` counter (labels: operation). Created
   `src/tta/observability/db_metrics.py` with `observe_db_query()` and
   `count_redis_op()` context managers. Callsite instrumentation deferred to
   persistence layer integration wave.

3. **Re-enabled DB pool exhaustion alert** (C5): Uncommented DBPoolExhausted
   alert in `monitoring/prometheus/alerts.yml`. Pool gauges already instrumented
   by `pool_metrics.py`.

4. **Input validation hardening** (H5): Added Pydantic `field_validator` to
   `SubmitTurnRequest` that strips zero-width Unicode characters (U+200B,
   U+200C, U+200D, U+2060, U+FEFF, U+FFFE). Whitespace-only input correctly
   triggers nudge flow — no rejection needed.

5. **Resume contextual recap** (FR-5.4): Resume endpoint now returns `recap`
   field: "When we last left off: {context_summary}" for games with turns,
   or derives from `world_seed.genesis.narrative_intro` for 0-turn resumes.
   Returns `None` when no summary available.

### Decisions

- **DB_CONNECTIONS_ACTIVE omitted**: Existing pool gauges (`tta_pg_pool_size`,
  `tta_pg_pool_checked_out`, etc.) already cover this. Redundant gauge would
  confuse operators.
- **Route labels use parameterized patterns** (e.g., `/api/v1/games/{game_id}`)
  not raw paths, preventing Prometheus cardinality explosion.
- **Zero-width char stripping, not rejection**: Pydantic validator silently
  strips invisible chars rather than returning 422, matching existing UX pattern
  where `input.strip()` normalizes whitespace.

## 22. Wave 19 — API Completeness & Observability Wiring

### Context

Gap analysis across S10, S12, S15 identified five concrete spec shortfalls:
turn history not paginated, CORS hardcoded, persistence metrics unwired,
SSE heartbeat not configurable, and env-based CORS parsing.

### Changes

1. **Turn history pagination** (`GET /{game_id}/turns`): New endpoint with
   cursor-based (base64-encoded turn_number) keyset pagination, N+1 fetch
   pattern, reuses existing `PaginationMeta` model. (S10 FR-10.13, S12 FR-12.03)
2. **CORS environment config**: Custom `_TtaEnvSource(EnvSettingsSource)` that
   overrides `decode_complex_value` to handle both JSON arrays and
   comma-separated strings for `TTA_CORS_ORIGINS`. (S10 FR-10.67)
3. **DB auto-instrumentation**: SQLAlchemy `before_cursor_execute` /
   `after_cursor_execute` event listeners on `engine.sync_engine` — automatically
   instruments all 74+ SQL call sites with zero per-site changes. Observes
   `DB_QUERY_DURATION` histogram with `database`/`operation` labels.
4. **Redis instrumentation**: All 3 Redis call sites (get, set, delete) in
   `redis_session.py` wrapped with `count_redis_op()`.
5. **SSE heartbeat configurability**: New `sse_heartbeat_interval` setting
   (default 15.0s) with range validator, wired into SSE stream generator.

### Stats

- 39 new unit tests (1480 total)
- 0 pyright errors, 0 ruff errors
- Files modified: `config.py`, `engine.py`, `redis_session.py`, `games.py`
- Files created: `tests/unit/test_wave19.py`

### Decisions

- **Engine-level instrumentation over per-site wrapping**: With 74 SQL call sites,
  SQLAlchemy event listeners provide universal coverage with no per-site changes
  and zero risk of missing sites.
- **Custom EnvSettingsSource for CORS**: pydantic-settings v2 calls
  `decode_complex_value()` → `json.loads()` for `list[str]` fields BEFORE field
  validators run. A custom source class is the only reliable way to support both
  JSON arrays and comma-separated strings.
- **Base64-encoded cursors**: Opaque to clients, allows changing internal
  representation (e.g., from turn_number to composite key) without breaking API.

## 23. Wave 20+ Recommendations

### Wave 20 — Production Polish & Hardening

1. Alertmanager integration for notification routing (PagerDuty, Slack, email)
2. Performance load testing and SLO validation against S28 targets
3. node_exporter for disk usage alerting (S15 FR-15.23)
4. Session token rotation (security improvement)
5. Live character state system (evolving traits beyond genesis)
6. Grafana dashboard JSON models for import

### Beyond v1

- S18-S22 future stubs (therapeutic framework, full crisis safety, sharing, co-authoring, community)
- Horizontal scaling, read replicas, CDN
