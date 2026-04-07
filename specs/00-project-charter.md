# S00 — Project Charter

> **Status**: 📝 Draft
> **Level**: 0 — Foundation
> **Dependencies**: None (this is the root)
> **Last Updated**: 2025-07-24

## 1. Purpose

This charter defines TTA's vision, values, success metrics, and boundaries. It is the
single document that every other spec, plan, and implementation decision traces back to.
If a feature doesn't serve this charter, it doesn't ship.

TTA is a text-based adventure game powered by AI. Players explore richly simulated worlds,
make meaningful choices, and experience stories that emerge from the interaction between
player agency and world simulation. The game is fun first — therapeutic value is a
long-term vision, not a v1 requirement.

## 2. Vision

**Create an AI-powered text adventure that generates stories so compelling, players want
to keep playing — and eventually, share what they've experienced.**

The game sits at the intersection of:
- **Interactive fiction** — player-driven narrative with real consequences
- **World simulation** — worlds that feel alive, with systems running underneath
- **AI generation** — every playthrough is unique, coherent, and surprising

## 3. Values (Ranked)

These values are ordered. When they conflict, higher values win.

1. **Fun** — If it's not fun, nothing else matters. Every feature must make the game
   more enjoyable, more surprising, or more satisfying.
2. **Coherence** — The world must make sense. Actions have consequences. NPCs remember.
   Time passes. Magic (or whatever system) follows rules.
3. **Player agency** — The player's choices must matter. Not "choose A or B" but genuine
   influence on the world state and story direction.
4. **Craftsmanship** — Clean code, tested behavior, honest documentation. No "we'll fix
   it later" unless it's in a spec with a ticket.
5. **Openness** — OSS-first. Transparent about what works and what doesn't. Build in the
   open when possible.

## 4. What TTA Is (v1)

- A single-player text adventure played in a browser
- AI-generated narrative that responds to player choices
- A simulated world with state, rules, and consequences
- An onboarding experience (Genesis) that creates your world and character
- A game you can save, resume, and replay with different choices

## 5. What TTA Is Not (v1)

- **Not a therapy app** — Therapeutic frameworks are a future vision (S18), not v1 scope
- **Not multiplayer** — Collaborative writing is future (S21)
- **Not a social platform** — Story sharing is future (S20), community is future (S22)
- **Not HIPAA-compliant** — We don't handle PHI in v1. Be honest about this.
- **Not a chatbot** — There is world state, simulation, progression, and narrative craft.
  This is not "ChatGPT with a fantasy skin."

## 6. Success Metrics

### Player Engagement
- **Session length**: Average play session > 15 minutes
- **Return rate**: > 40% of players return for a second session
- **Story completion**: > 25% of players reach a meaningful story milestone

### Technical Quality
- **Response latency**: < 3 seconds p95 from input to first narrative token
- **Coherence**: < 5% of turns produce narrative contradictions (measured by review)
- **Uptime**: 99% availability during active development (not production SLA yet)

### Development Velocity
- **Spec-to-implementation**: Each spec can be implemented in ≤ 2 weeks
- **Test coverage**: ≥ 80% for all game-critical paths
- **Zero broken main**: CI gate prevents merging code that fails tests

## 7. Scope Fences

### The v1 Fence
Everything inside this fence ships in v1. Everything outside is a future spec stub.

**Inside v1:**
- Single-player gameplay loop with AI narrative
- Genesis onboarding (world + character creation)
- World simulation with state and consequences
- Character system (PC + NPCs)
- Save/resume sessions
- SSE-based streaming API
- Basic player accounts
- Single deployment target (Docker Compose)

**Outside v1 (future stubs exist):**
- Therapeutic framework integration (S18)
- Crisis detection and content safety systems (S19)
- Story sharing and export (S20)
- Collaborative/multiplayer writing (S21)
- Community features, moderation, discovery (S22)

### The "Not Our Code" Fence
We do not build what OSS provides. Specifically:

| Need | Solution | We Do NOT Build |
|------|----------|----------------|
| LLM routing/fallback | LiteLLM | Custom model cascade |
| Workflow orchestration | LangGraph | Custom agent framework |
| Retry/resilience | tenacity | Custom circuit breakers |
| Observability | Langfuse + OpenTelemetry | Custom tracing primitives |
| API framework | FastAPI | Custom HTTP layer |
| Auth | OSS auth library (TBD) | Custom auth system |
| Graph database | Neo4j | Custom graph engine |

## 8. Legacy Assumptions Audit

These are decisions from the old TTA that we've explicitly reconsidered:

| Old Decision | Old Rationale | v1 Verdict | Why |
|---|---|---|---|
| TTA.dev as a separate library | "Universal primitives" | **Drop** | tenacity, LangGraph, and OSS handle this |
| Custom circuit breaker (Redis-backed) | Reliability | **Drop** | tenacity + LangGraph retry |
| Custom observability primitives | Pipeline tracing | **Drop** | Langfuse + OTEL |
| Unit of Work + Manager + Repository | Clean architecture | **Simplify** | SQLModel repos are enough |
| 5 separate API servers | Microservices | **Merge** | One FastAPI app with RBAC |
| Dolt for versioned player data | Time-travel queries | **Defer** | Not needed for v1 |
| HIPAA compliance | Therapeutic app | **Defer** | We don't handle PHI yet |
| WebSocket + SSE dual transport | Real-time + streaming | **SSE only** | WS for multiplayer later |
| 9-tier LLM model cascade | Cost optimization | **Simplify** | 2-3 tier fallback via LiteLLM |
| Neo4j for player data | Graph fits everything | **Split** | Neo4j=world, SQL=players |
| IPA→WBA→NGA as 3 distinct agents | Separation of concerns | **Spec behavior** | Spec the pipeline behavior, not the agent decomposition |
| Safety systems in core loop | Player protection | **Defer** | Future release, not v1 |

## 9. Testing Philosophy

Testing is not an afterthought — it's baked into the spec process.

### Every Spec Includes Testable Acceptance Criteria
- Each AC maps to one or more automated tests
- "Acceptance criteria met" = "tests pass"
- If an AC can't be automated, it must say why and define a manual verification process

### Test Pyramid
- **Unit tests** (70%): Fast, isolated, test single functions/methods
- **Integration tests** (20%): Test component interactions (DB, LLM mocks, API)
- **E2E tests** (10%): Test complete user journeys through the API

### Coverage Targets
- Game-critical paths (gameplay, narrative, world state): ≥ 80%
- Platform (API, auth, sessions): ≥ 70%
- Infrastructure (deployment, CI): ≥ 60%

### CI Gate
No merge to main without:
- All tests passing
- Coverage thresholds met
- Linting clean (ruff)
- Type checking clean (pyright)

## 10. Technology Direction

> **Note**: Technology choices are **guidance**, not mandates. Each spec may challenge
> these defaults if a better option exists. The Plan phase will finalize the stack.

| Layer | Likely Choice | Rationale |
|-------|--------------|-----------|
| Language | Python 3.12+ | AI/ML ecosystem, team familiarity |
| Package manager | uv | Fast, reliable, replaces pip |
| API framework | FastAPI | Async, typed, SSE support |
| Workflow engine | LangGraph | Graph-based agent orchestration |
| LLM gateway | LiteLLM | Unified API for 100+ models |
| LLM observability | Langfuse | Open-source, self-hostable |
| World graph | Neo4j | Native graph DB for world state |
| Player data | SQLite/PostgreSQL via SQLModel | Simple relational for player state |
| Cache/messaging | Redis | Session cache, pub/sub |
| Resilience | tenacity | Retry with backoff, well-maintained |
| Linting | ruff | Fast, comprehensive |
| Type checking | pyright | Standard mode |
| Testing | pytest | asyncio-auto, comprehensive |
| Containerization | Docker Compose | Single-machine deployment for v1 |

## 11. Spec Conventions

All specs in this repo follow these conventions:

1. **Behavior-focused**: Describe *what* the system does, not *how* it's built
2. **Template-based**: Use `specs/TEMPLATE.md` for consistent structure
3. **Cross-referenced**: Dependencies between specs are explicit, with boundary contracts
4. **Testable via Gherkin**: Acceptance criteria use Given/When/Then syntax (Gherkin)
   so they can be directly executed as automated BDD tests (e.g., via Behave or pytest-bdd)
5. **Scoped**: "Out of Scope" sections prevent creep, with redirects to the right spec
6. **Honest**: Open questions are documented with impact level, not hidden
7. **Goldilocks detail**: Enough to remove ambiguity, not so much it reads like pseudo-code.
   If there's only one reasonable interpretation, don't belabor it.
8. **Structurally modular**: Functional spec (what) is separate from technical plan (how)
   and task breakdown — so each phase fits cleanly in an AI agent's context window

## 12. Acceptance Criteria

- [ ] **AC-1**: All 23 specs exist with complete content following the template
- [ ] **AC-2**: Every spec has testable acceptance criteria
- [ ] **AC-3**: Spec dependency graph is acyclic and documented
- [ ] **AC-4**: Legacy assumptions are explicitly addressed (kept, dropped, or deferred)
- [ ] **AC-5**: v1 scope fence is unambiguous — any feature can be classified as in/out
- [ ] **AC-6**: Technology direction is documented as guidance, not mandates
- [ ] **AC-7**: Testing philosophy is defined with measurable targets

## 13. Open Questions

1. What is the permanent name for this project/repo?
2. What license should we use? (AGPL, MIT, proprietary?)
3. Do we want a public roadmap beyond the spec stubs?
4. Should we use a specific frontend framework or stay API-only for v1?
5. How do we handle AI-generated content attribution?

## 14. Out of Scope

- Implementation details (that's the Plan phase)
- Specific API endpoint designs (see S10)
- Database schema details (see S12, S13)
- Deployment topology (see S14)
- Any feature outside the v1 fence
