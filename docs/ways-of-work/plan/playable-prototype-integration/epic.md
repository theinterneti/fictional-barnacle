# Epic PRD: Playable Prototype Integration

**Epic Name:** Playable Prototype Integration
**Epic ID:** EPIC-01
**Created:** 2025-07-28
**Status:** Draft

---

## 1. Epic Name

**Playable Prototype Integration** — End-to-end demonstration that all v1 game systems work together as a cohesive, playable experience.

---

## 2. Goal

### Problem

TTA has 35+ development waves of implemented subsystems across auth, genesis, turn pipeline, world model, character system, persistence, streaming API, observability, and more. Each subsystem has been developed and tested in relative isolation through spec-driven waves. What does **not yet exist** is a validated, end-to-end integration demonstrating that a real player can sit down, create a game world, play through narrative turns, make choices with consequences, and return to their session — all working seamlessly together. The risk is that individually-correct subsystems have integration gaps, incompatible contracts, or broken orchestration paths that only surface when they run together.

### Solution

Define and exercise a complete vertical slice of TTA: anonymous player registration → Genesis onboarding → turn-based gameplay with SSE streaming → world state updates → choice/consequence propagation → save/resume. This epic is about **integration validation**, not new feature development. It produces a Docker-Compose-deployable prototype where all 8 v1 scope items from the Project Charter (S00) demonstrably function together. Spec compliance gaps discovered during integration become fast-follow wave issues; the goal here is a running, connected system.

### Impact

- Provides the first concrete "does TTA work as a game?" answer
- Exposes cross-subsystem contract mismatches before they accumulate further
- Gives stakeholders and collaborators a tangible artifact to play-test
- Establishes a stable integration baseline against which future compliance waves can be validated

---

## 3. User Personas

### Primary Persona: The Curious Playtester
A developer, contributor, or early-access user who wants to experience TTA as a game — not audit its code. They will `docker compose up`, open the static client in a browser, complete Genesis, and play 3–10 turns of narrative adventure. They have no interest in the internals; they care whether the game feels responsive, narratively coherent, and retains their progress.

### Secondary Persona: The Integration Validator
A developer or QA contributor who runs the E2E test suite to confirm all subsystems communicate correctly. They want confidence that changes to one subsystem (e.g., world model) do not silently break another (e.g., narrative generation). They work through `make test` and the BDD suite, not the browser.

### Tertiary Persona: The Ops Operator
A developer who deploys and monitors TTA in a local or staging environment. They want the Docker Compose stack to start cleanly, health checks to pass, logs to be structured and traceable, and the system to recover from transient failures (LLM timeouts, Redis misses) without crashing.

---

## 4. High-Level User Journeys

### Journey 1: First-Time Player — Genesis to First Turn

1. Player opens the static client (`/static/index.html` or similar) in a browser
2. Player clicks "New Game" — anonymous session is created (S11), consent accepted
3. Genesis onboarding begins (S02): player answers world-building prompts (genre, tone, starting scenario)
4. World is initialized: world model record created in PostgreSQL, world graph seeded in Neo4j (S13)
5. Opening narrative is generated via LLM and streamed to the client via SSE (S07, S08, S10)
6. Player sees their first choices (S05) and selects one
7. Turn pipeline processes the choice: intent classification → world enrichment → narrative generation → streaming response (S08)
8. World state is updated to reflect the consequence of the choice (S04, S05)

### Journey 2: Returning Player — Save and Resume

1. Player returns to the static client after closing their browser
2. Player resumes their existing game session using their anonymous token (S11, S27)
3. Context summary is displayed (S03 summary feature)
4. Player continues from where they left off — world state, character state, and narrative history intact (S12)

### Journey 3: Integration Validator — E2E Test Run

1. Developer runs `make test` or the dedicated BDD/integration test target
2. Integration tests exercise the full turn pipeline against a live Docker Compose stack
3. All critical user journeys pass with defined latency bounds
4. Logs are structured, correlated by request ID, and emitted to stdout for collection

### Journey 4: Ops Operator — Stack Startup and Health

1. Operator runs `docker compose up`
2. All services start: FastAPI, PostgreSQL, Neo4j, Redis
3. Health endpoints return `200 OK` once all dependencies are ready (`/api/v1/health`, `/api/v1/health/ready`)
4. A test Genesis + first turn runs successfully, confirming end-to-end connectivity

---

## 5. Business Requirements

### Functional Requirements

#### Player Identity & Session (S11)
- Anonymous player registration creates a session token (no email/password required)
- Consent acknowledgement is recorded at registration
- Session token authenticates all subsequent game API calls
- Sessions persist across browser restarts (token stored in client)

#### Genesis Onboarding (S02)
- Player is guided through at least: genre selection, tone selection, world name, starting scenario description
- Genesis inputs are validated and stored as world-initialization parameters
- World and first game session are created upon Genesis completion
- Player receives their first narrative turn immediately after Genesis

#### Gameplay Loop (S01, S03, S04, S05, S06)
- Each turn: player input → intent classification → world state read → narrative generation → choices offered
- Narrative is generated by an LLM (via LiteLLM, S07) and streamed to the client (SSE, S10)
- Choices are mechanically valid (at least 2 per turn, consistent with world state)
- World state is updated after each turn (location, NPC states, inventory if applicable)
- Character state (PC + active NPCs) is maintained and referenced in narrative

#### Turn Pipeline (S08)
- All 5 pipeline stages execute in sequence: Understand → Enrich → Generate → Stream → Persist
- Pipeline errors are caught, logged, and return a graceful error response to the client (S23)
- Turn latency (time-to-first-token) is ≤ 3 seconds under normal conditions

#### Persistence (S12, S27)
- Game state is persisted to PostgreSQL after each turn
- Session cache (Redis) is used for active games; PostgreSQL is authoritative
- Save/resume works: a player who re-authenticates can continue their game
- Game can be soft-deleted (abandoned) by the player

#### Streaming API (S10)
- SSE endpoint streams narrative tokens as they are generated
- API returns structured error responses per S23 error envelope
- Rate limiting is applied per player (S25)

#### Observability (S15)
- All API requests log a `request_id` (correlation ID) in structured JSON
- LLM call latency and token usage are recorded as Prometheus metrics
- Health endpoints expose readiness for all downstream dependencies

#### Deployment (S14)
- `docker compose up` starts the full stack (FastAPI, PostgreSQL 16, Neo4j CE 5, Redis 7)
- Environment variables are the sole configuration mechanism; no secrets in images
- Stack passes health checks within 60 seconds of startup

### Non-Functional Requirements

- **Latency**: Time-to-first-token for narrative generation ≤ 3 seconds at p95 under single-user load
- **Correctness**: World state after N turns must be deterministically reconstructable from the turn history
- **Resilience**: LLM timeout or provider error returns a graceful fallback response without crashing the stack (S23 retry/circuit-breaker via tenacity)
- **Security**: No secrets committed to version control; anonymous tokens are non-guessable (UUID v4 minimum); all endpoints require valid session auth except registration and health
- **Privacy**: Player data collected is limited to what's required for gameplay; consent is recorded at registration (S17)
- **Portability**: The Docker Compose stack runs on any x86_64 Linux/macOS machine with Docker installed; no platform-specific dependencies
- **Testability**: Integration tests run against the Docker Compose stack; tests are idempotent and leave no persistent state between runs

---

## 6. Success Metrics

| Metric | Target | How Measured |
|---|---|---|
| E2E test pass rate | 100% green on all Journey 1–4 scenarios | `make test` / BDD suite |
| `docker compose up` to health-ready | ≤ 60 seconds | Automated stack startup test |
| Turn latency (time-to-first-token) | ≤ 3s at p95, single user | Integration test with timing assertions |
| Save/resume correctness | Resumed game state matches last persisted state | Integration test comparing turn N+1 context |
| Log correlation coverage | 100% of API requests carry `request_id` in logs | Log inspection in integration tests |
| Zero subsystem startup failures | All health checks pass on first clean `docker compose up` | CI stack startup job |
| Play-tester onboarding | A new developer can complete Genesis + 3 turns within 10 minutes of `git clone` | Manual walkthrough |

---

## 7. Out of Scope

The following are explicitly **not** part of this epic:

- **Full per-AC spec compliance** — Individual spec compliance audits continue as separate wave work. This epic validates integration, not completeness of every acceptance criterion.
- **Therapeutic framework** (S18) — Future stub; not v1 scope per Project Charter
- **Crisis detection / content safety systems** (S19) — Future stub
- **Story sharing / export** (S20) — Future stub
- **Collaborative / multiplayer writing** (S21) — Future stub
- **Community features** (S22) — Future stub
- **Admin operator UI** (S26) — Admin API endpoints may be present but a UI is not required for this epic
- **Performance at scale** (S28) — Single-user prototype performance is in scope; load testing and horizontal scaling are not
- **World Graph advanced queries** (S13 beyond basic schema) — World graph must exist and seed; complex traversal queries are not required for this epic
- **Content moderation pipeline** (S24) — Basic prompt safety guardrails from S09 are in scope; a full moderation review workflow is not
- **Email-based player accounts** — Anonymous sessions only; no email/password auth is required for the prototype

---

## 8. Business Value

**Value Rating: High**

**Justification:**

TTA has invested 35+ development waves into building subsystems. Without integration validation, this investment exists as a collection of individually-correct components that may or may not form a working game. A playable prototype:

1. **De-risks the project** by surfacing integration gaps before they compound further
2. **Creates a tangible milestone** — "it works as a game" — that can be communicated to collaborators and early testers
3. **Establishes a regression baseline** — future spec compliance waves have a running system to validate against, instead of test-only verification
4. **Enables play-testing** — real feedback from playing the game will surface UX and narrative quality issues that specification cannot predict
5. **Unlocks downstream work** — therapeutic framework integration (S18/S19), sharing features (S20), and community features (S22) all depend on a stable game loop

The cost of not doing this epic is continued spec-compliance work against a system that has never been validated as a whole — increasing the risk that integration issues discovered later require architectural changes.

---

## Appendix: Spec Coverage Map

| Epic Requirement | Primary Specs | Status |
|---|---|---|
| Player Identity & Session | S11 | Draft |
| Genesis Onboarding | S02 | Draft |
| Gameplay Loop | S01, S03, S04, S05, S06 | Draft |
| LLM Integration | S07 | Draft |
| Turn Processing Pipeline | S08 | Draft |
| Prompt Management | S09 | Draft |
| Streaming API | S10 | Draft |
| Error Handling | S23 | Draft |
| Rate Limiting | S25 | Draft |
| Persistence | S12 | Partial |
| Save/Load | S27 | Draft |
| Observability | S15 | Draft |
| Deployment | S14 | Draft |
| Privacy / Consent | S17 | Draft |

> **Note:** All specs are in "Draft" status in `specs/index.json`. This epic does not require specs to be promoted to "Final" — it requires the corresponding *code* to integrate correctly. Spec promotion is a separate concern.

---

## Appendix: Decomposition Note (PM Answer to Original Question)

> *"Would unifying all specs into a working prototype be an appropriate epic?"*

**Yes — with a scoped definition of "working prototype."**

"Unifying all 29 specs into full spec compliance" would be 4–5 epics. But "unifying the existing implementation into a demonstrably playable game" is exactly one epic. The distinction is:

- ❌ **Too broad**: "Implement all ACs across all 29 specs" — this is the sum of all remaining wave work
- ✅ **This epic**: "Validate that existing implementations integrate end-to-end into a playable game"
- ✅ **Downstream epics** (post-prototype): Per-pillar spec compliance (Core Game, AI Pipeline, Platform, Ops)

The 35+ waves of work already done are the raw material. This epic is the integration test that proves the raw material coheres.
