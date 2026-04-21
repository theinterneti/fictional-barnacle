# Spec Index

Status tracker for all TTA specifications. Each spec follows the [template](TEMPLATE.md).

## Status Legend

| Status | Meaning |
|--------|---------|
| 📝 Draft | Initial version written, not yet reviewed |
| 🔍 Review | Under review, accepting feedback |
| ✅ Approved | Reviewed and accepted as source of truth |
| 🔄 Revised | Updated after implementation feedback |
| 🔒 v1 Closed | Retrospective section added; no further normative changes |

## Level 0: Foundation

| # | Spec | Status | v1 Baseline | Description |
|---|------|--------|-------------|-------------|
| S00 | [Project Charter](00-project-charter.md) | 📝 Draft | 🔒 v1 Closed | Vision, values, scope fences, testing philosophy |

## Level 1: Core Game Experience

| # | Spec | Status | v1 Baseline | Description |
|---|------|--------|-------------|-------------|
| S01 | [Gameplay Loop & Progression](01-gameplay-loop.md) | 📝 Draft | 🔒 v1 Closed | Moment-to-moment play, meta-loop, saves |
| S02 | [Genesis Onboarding](02-genesis-onboarding.md) | 📝 Draft | 🔒 v1 Closed | 5-act new player journey |
| S03 | [Narrative Engine](03-narrative-engine.md) | 📝 Draft | 🔒 v1 Closed | Story generation, narrator voice, coherence |
| S04 | [World Model](04-world-model.md) | 📝 Draft | 🔒 v1 Closed | World structure, state, simulation rules |
| S05 | [Choice & Consequence](05-choice-and-consequence.md) | 📝 Draft | 🔒 v1 Closed | Player agency, branching, impact |
| S06 | [Character System](06-character-system.md) | 📝 Draft | 🔒 v1 Closed | PCs, NPCs, relationships, development |

## Level 1b: Core Game (Extended)

| # | Spec | Status | v1 Baseline | Description |
|---|------|--------|-------------|-------------|
| S27 | [Save/Load & Game Management](27-save-load-and-game-management.md) | 📝 Draft | 🔒 v1 Closed | Game lifecycle, auto-save, listing, resume, deletion |

## Level 2: AI & Content

| # | Spec | Status | v1 Baseline | Description |
|---|------|--------|-------------|-------------|
| S07 | [LLM Integration](07-llm-integration.md) | 📝 Draft | 🔒 v1 Closed | Model abstraction, streaming, fallbacks |
| S08 | [Turn Processing Pipeline](08-turn-processing-pipeline.md) | 📝 Draft | 🔒 v1 Closed | Input→Context→Narrative behavior |
| S09 | [Prompt & Content Management](09-prompt-and-content.md) | 📝 Draft | 🔒 v1 Closed | Prompt versioning, authoring, testing |
| S24 | [Content Moderation v1](24-content-moderation-v1.md) | 📝 Draft | 🔒 v1 Closed | Input/output moderation, flagging, audit trail |

## Level 3: Platform

| # | Spec | Status | v1 Baseline | Description |
|---|------|--------|-------------|-------------|
| S10 | [API & Streaming](10-api-and-streaming.md) | 📝 Draft | 🔒 v1 Closed | REST + SSE contracts |
| S11 | [Player Identity & Sessions](11-player-identity-and-sessions.md) | 📝 Draft | 🔒 v1 Closed | Auth, profiles, session lifecycle |
| S12 | [Persistence Strategy](12-persistence-strategy.md) | 📝 Draft | 🔒 v1 Closed | Storage requirements → tech choices |
| S13 | [World Graph Schema](13-world-graph-schema.md) | 📝 Draft | 🔒 v1 Closed | Graph schema for world state |
| S23 | [Error Handling & Resilience](23-error-handling-and-resilience.md) | 📝 Draft | 🔒 v1 Closed | Error taxonomy, retries, circuit-breakers, turn atomicity |
| S25 | [Rate Limiting & Anti-Abuse](25-rate-limiting-and-anti-abuse.md) | 📝 Draft | 🔒 v1 Closed | Per-player/IP rate limits, sliding window, anti-abuse |

## Level 4: Operations

| # | Spec | Status | v1 Baseline | Description |
|---|------|--------|-------------|-------------|
| S14 | [Deployment & Infrastructure](14-deployment.md) | 📝 Draft | 🔒 v1 Closed | Docker, CI/CD, environments |
| S15 | [Observability](15-observability.md) | 📝 Draft | 🔒 v1 Closed | Logging, metrics, tracing |
| S16 | [Testing Infrastructure](16-testing-infrastructure.md) | 📝 Draft | 🔒 v1 Closed | CI gates, coverage, test environments |
| S17 | [Data Privacy](17-data-privacy.md) | 📝 Draft | 🔒 v1 Closed | GDPR, retention, encryption |
| S26 | [Admin & Operator Tooling](26-admin-and-operator-tooling.md) | 📝 Draft | 🔒 v1 Closed | Admin API, player management, audit log |
| S28 | [Performance & Scaling](28-performance-and-scaling.md) | 📝 Draft | 🔒 v1 Closed | Latency budgets, throughput, scaling readiness |

## Level 5: Future (Boundary Stubs)

These are **not full specs**. They define boundaries and constraints on v1 design to ensure future compatibility, without specifying the future features themselves.

| # | Spec | Status | v1 Baseline | Description |
|---|------|--------|-------------|-------------|
| S18 | [Therapeutic Framework](future/18-therapeutic-framework.md) | 📝 Stub | — | Boundary constraints for therapy integration |
| S19 | [Crisis & Content Safety](future/19-crisis-and-content-safety.md) | 📝 Stub | — | Boundary constraints for safety systems |
| S20 | [Story Sharing](future/20-story-sharing.md) | 📝 Stub | — | Boundary constraints for shareable stories |
| S21 | [Collaborative Writing](future/21-collaborative-writing.md) | 📝 Stub | — | Boundary constraints for co-authoring |
| S22 | [Community](future/22-community.md) | 📝 Stub | — | Boundary constraints for player community |

## Dependency Graph

```
S00 (Charter)
 ├── S01-S06 (Core Game)  ← The heart. Write these first.
 │    └── S27 (Save/Load) ← Game lifecycle atop S01, S02
 ├── S07 (LLM Integration) ← Enables S08
 │    └── S08 (Turn Pipeline) ← Consumes S01-S06 + S07
 │         ├── S09 (Prompts) ← Content layer over S08
 │         └── S24 (Content Moderation v1) ← Filters S08 output, fills S19 gap
 ├── S10-S11 (API, Identity) ← Platform for S01-S06
 ├── S12 (Persistence) ← Storage for S04, S06, S11
 │    └── S13 (World Graph) ← Schema for S04 specifically
 ├── S23 (Error Handling) ← Cross-cutting, referenced by most specs
 ├── S25 (Rate Limiting) ← Depends on S11, S23
 ├── S14-S17 (Ops) ← Cross-cutting, can be written in parallel
 ├── S26 (Admin Tooling) ← Depends on S11, S23, S24, S25
 ├── S28 (Performance) ← Capstone, references all platform specs
 └── S18-S22 (Future) ← Stubs, boundary constraints only
```

## Reserved Spec IDs — v2+ (Post-v1 Roadmap)

IDs S29–S63 are reserved for post-v1 releases. They are not yet full specs; they
will be drafted via individual brainstorm sessions following the SDD workflow.
See [`docs/superpowers/specs/2026-04-21-v2-v3-roadmap-design.md`](../docs/superpowers/specs/2026-04-21-v2-v3-roadmap-design.md)
for the full roadmap rationale, dependency graph, and open questions per spec.

### v2.0 — "Believable Simulation" (S29–S40)

| # | Name | Description |
|---|------|-------------|
| S29 | [Universe as First-Class Entity](29-universe-as-first-class-entity.md) | Universe identity, config, persistent state — not a session appendage |
| [S30](30-session-universe-binding.md) | Session↔Universe Binding | Explicit 1:1 binding contract; schema permits n:1 for v4+ |
| [S31](31-actor-identity-portability.md) | Actor Identity Portability | Actor IDs universe-agnostic; unblocks cross-universe travel |
| [S32](32-transport-abstraction.md) | Transport Abstraction | `NarrativeTransport` interface; SSE as first impl, WebSocket-ready |
| [S33](33-universe-persistence-schema.md) | Universe Persistence Schema | Versioned forward-compat state envelope; enables universe reload |
| S34 | Diegetic Time | In-world clock; day/night cycles, scene transitions, skip-ahead |
| S35 | NPC Autonomy Between Turns | Off-screen NPC goals, routines, salience filter (no LangGraph) |
| S36 | Consequence Propagation | Effect ripple via graph-walk, bounded depth, rumor distortion |
| S37 | World Memory Model | Canon events, decay, compression, structured attributed memory |
| S38 | NPC Memory Model | Per-NPC episodic memory; relationship-graph arcs; v4+ multiplayer hook |
| S39 | Universe Composition Model | Themes, tropes, archetypes, genre-twists; composable, seedable, deterministic from (seed, config) |
| S40 | Genesis v2 | 7-phase world-creation; consumes S39 composition vocabulary |

### v2.1 — "Prove It's Fun" (S41–S45)

| # | Name | Description |
|---|------|-------------|
| S41 | Scenario Seed Library | Curated/community scenario seeds; YAML/JSON format; discovery registry |
| S42 | LLM Playtester Agent Harness | LLM-persona agents; semi-randomized taste profiles; end-to-end session runs; transcript + commentary |
| S43 | Human Playtester Program | Recruitment, consent, NDA; structured feedback protocol |
| S44 | Narrative Quality Evaluation | Scoring rubric; 0–1 normalisation; LLM + human signal weighting |
| S45 | Evaluation Pipeline | Orchestration of parallel LLM-playtester runs; human-playtester intake; result aggregation; CI thresholds |

### v3 — "Ship It" (S46–S49)

| # | Name | Description |
|---|------|-------------|
| S46 | Cloud Deployment v2 | Fly.io / Cloud Run; live-DB CI; TLS; secrets rotation |
| S47 | Live Neo4j in CI | Ephemeral Neo4j per test run; replaces mocked integration tests; fixture setup/teardown |
| S48 | Async Job Runner | Job queue + worker for GDPR deletion, retention sweeps, backfills; worker permitted alongside FastAPI process |
| S49 | Horizontal Scaling | Session affinity policy; Redis cluster; load-balancer config |

### v4+ — "Multiverse Unlock" (S50–S59)

| # | Name | Description |
|---|------|-------------|
| S50 | Concurrent Universe Loading | Two or more universes resident in memory simultaneously; resource-budget rules, eviction policy, isolation guarantees |
| S51 | Cross-Universe Travel Protocol | Actor movement from Universe A to Universe B; trigger conditions, state-transfer rules, arrival onboarding |
| S52 | Nexus as Special Universe | Nexus modeled as a universe whose composition permits inhabitants from any other universe; no engine-level hub special case |
| S53 | Nexus Access Rules | Narrative triggers and gating for reaching the Nexus; the *story* of why players find it, separate from its mechanics (S52) |
| S54 | Inter-Universe Event Substrate | Communication bus between loaded universes; pure primitive, no semantics; delivery guarantees and ordering rules |
| S55 | Bleedthrough Propagation Rules | Semantics of subtle inter-universe influence on S54; weather anomalies, rumors, echoes; probabilistic distortion rules |
| S56 | Resonance Correlation Engine | Thematic echoes: a choice in Universe A biases narrative weight in Universe B along shared S39 themes; correlation rules, strength decay |
| S57 | Multi-Actor Universe Model | Multiple actors coexist in one universe; promotes v1 S21; shared world-state semantics, per-actor narrative perspective |
| S58 | Turn Conflict Resolution | Simultaneous/contradictory actor actions; ordering rules, priority, narrative reconciliation |
| S59 | Multiplayer Transport | WebSocket implementation of S32 `NarrativeTransport` interface; session-level sync, presence, reconnection |

### v5+ — "Long Vision" (S60–S63, promotes v1 stubs)

| # | Promotes | Description |
|---|----------|-------------|
| S60 | v1 S19 Crisis Safety | **Gate** for S61. Crisis detection, escalation, clinician-notify |
| S61 | v1 S18 Therapeutic Framework | CBT + Mindfulness MVP; therapeutic annotation layer |
| S62 | v1 S20 Story Sharing | PDF/ePub/web export; consent model; public story library |
| S63 | v1 S22 Community | User-generated world templates; moderation; attribution |

> **Note**: v1 stubs S18–S22 remain frozen at `specs/future/` until the relevant
> v5+ spec is drafted. S21 is **not** promoted via this table; it is superseded by
> S57–S59 (v4+) which provide a more complete multiplayer foundation.

---

## Conventions

- Specs are **behavior-focused**, not implementation-prescriptive
- Each spec is self-contained but cross-references dependencies
- "Out of Scope" sections are explicit — they prevent scope creep
- Acceptance criteria are testable — each one maps to a verifiable assertion
- Open questions are documented honestly, not papered over
