# v2 / v3 / v4+ / v5+ Roadmap — Design Document

> **Status**: ✅ Approved — repo changes applied
> **Created**: 2026-04-21
> **Revised**: 2026-04-21 (iteration 2: applied HIGH+MEDIUM fixes from reviewer)
> **Author**: Claude Code session (brainstorming skill)
> **Scope**: Release planning and atomic-spec decomposition for all post-v1 work.
> **Next artifacts**: Individual specs (S29–S63), each via its own brainstorm.
> **Normative?**: No. This is a planning document. The specs it references are
> normative; this document is the map to them.

---

## 1. Product Thesis

TTA v1 shipped a playable, single-session, locally-deployed narrative engine
(v1 closed 2026-04-XX; 24 specs, S00–S17 + S23–S28). v1 was deliberately scoped
to the smallest shippable thing. The post-v1 roadmap is organized around a clear
ordering of *product* over *platform*:

| Release | One-line thesis |
|---|---|
| **v2.0** | *"An utterly believable simulation."* Make each session's world feel alive. |
| **v2.1** | *"Prove it's fun."* LLM-persona playtesters + curated human playtester program validate narrative quality. |
| **v3** | *"Ship it where people can play."* Cloud deployment, live-DB CI, async workers, horizontal scale. |
| **v4+** | *"Multiverse unlock."* Nexus, cross-universe travel, Bleedthrough, Resonance, multiplayer. |
| **v5+** | *"The long vision."* Crisis Safety (gate), Therapeutic Framework MVP, Story Sharing, Community. |

This ordering **inverts the implicit priority in the v1 charter** (which listed
deployment as "What v2 Must Address"). The reasoning: v1 is functionally
complete but narratively thin. Deploying a thin experience to more users is
less valuable than making the experience compelling first.

**The v2 product thesis in one sentence**: *an open-ended parallel-universes
storytelling game backed by an utterly believable simulation.*

---

## 2. Release Lineup

35 new specs total, numbered contiguously S29–S63. Plus minor AC additions to
four v1 specs (S04, S08, S10, S15).

| Release | Count | IDs | Focus |
|---|---|---|---|
| **v2.0** | 12 | S29–S40 | Forward-compat architecture + Believable Simulation + Genesis v2 |
| **v2.1** | 5 | S41–S45 | Scenario Seed Library + LLM Playtesters + Human Playtester Program + Evaluation |
| **v3** | 4 + 1 ext | S46–S49 | Cloud, live Neo4j CI, async jobs, scaling (+ v1 S15 alert runbook-link extension) |
| **v4+** | 10 | S50–S59 | Multi-universe infra, Nexus, Bleedthrough, Resonance, multiplayer |
| **v5+** | 4 | S60–S63 | Crisis Safety, Therapeutic MVP, Story Sharing, Community |

---

## 3. v2.0 — "Utterly Believable" (12 specs)

Ships the richer simulation and narrator-arc Genesis. Externally demo-able.
User-visible improvement over v1.

### 3.1 Forward-compat architecture (S29–S33)

These exist to make v4+ features a no-breaking-change addition. Each is
cheap to ship now and expensive to retrofit later.

| ID | Name | One-paragraph summary |
|---|---|---|
| **S29** | Universe as First-Class Entity | A universe has its own identity, config, and persistent state — it is not a session appendage. v2 sessions each own exactly one universe by policy, but the schema permits n:1. Every world-scoped entity (location, item, NPC, faction) stores `universe_id`. |
| **S30** | Session↔Universe Binding | Explicit binding contract between a session and a universe. In v2 the binding is 1:1 and enforced at application level, but the session schema stores `actors: list[ActorId]` with length=1 so multi-actor adoption in v4+ is additive. |
| **S31** | Actor Identity Portability | Actor IDs are universe-agnostic; character state is universe-scoped. In v2 an actor exists in exactly one universe at a time, but the identity model does not *couple* actor to universe. Unblocks cross-universe travel (S51) without a rewrite. |
| **S32** | Transport Abstraction | SSE becomes one implementation of a `NarrativeTransport` interface. Narrative-delivery code does not import SSE types directly. Resolves the unmet S21 constraint flagged in v1 closeout. WebSocket can be added later (S59) without touching stages above the transport. |
| **S33** | Universe Persistence Schema | Versioned, forward-compat universe state envelope. Generic persistence mechanism — the *shape* of persisted content is defined by S39. Enables "reload this universe next session" (player-facing value in v2) and concurrent universe loading (v4+). Schema version lives alongside migration path. |

**Dependencies**: S30 → S29. S31 → S29. S33 → S29, v1 S12, v1 S13. S32 → v1 S10.

### 3.2 Believable Simulation (S34–S38)

The "utterly believable" pillar. v1's simulation was shallow — NPCs have no
between-turn life, consequences don't propagate, memory is linear. v2.0 fixes
each of these as its own spec.

| ID | Name | One-paragraph summary |
|---|---|---|
| **S34** | Diegetic Time | An in-world clock. Mapping rules from real-time to world-time. Day/night cycles, scene transitions, skip-ahead mechanics, sleep/rest. Foundation primitive consumed by S35/S36/S37. |
| **S35** | NPC Autonomy Between Turns | NPCs pursue goals off-screen. Routines (the butcher closes shop at dusk), off-screen events (the king dies while the player is away), reactivity to distant triggers. Uses a salience filter — not every NPC is modeled every turn. **This is not a multi-agent orchestration framework; no LangGraph or agent-router is introduced. The charter's §10 rejection of 10-agent decomposition stands.** |
| **S36** | Consequence Propagation | When the player acts, effects ripple across locations, NPCs, and factions via graph-walk rules. Bounded depth. Distant locations "hear rumors" with distortion. Makes the world feel like it exists outside the player's POV. |
| **S37** | World Memory Model | Canon events, decay, compression, persistence. v1's conversation history is a flat string dump produced by the turn pipeline; v2 needs a structured, attributed, time-aware memory model. Compression threshold and summarization rules. Foundation for story export (S62 in v5+). |
| **S38** | NPC Memory & Social Model | Distinct from world memory: per-NPC recollection of the player — trust, grudges, affection, gossip. NPCs remember the player across sessions. Shared social graph so gossip propagates. |

**Dependencies**: S34 → S29. S35 → S34. S36 → S34, S35, v1 S04. S37 → v1 S03, v1 S08, v1 S12, v1 S13. S38 → S33, S35, S37, v1 S06.

### 3.3 Wonder & Narrative (S39–S40)

The composition and onboarding primitives. These replace the v1 Genesis spec
with something that carries the real-to-strange narrator arc described in the
old TTA design docs.

**Clarifying note on S29 / S33 / S39.** These three specs address three
*orthogonal* aspects of "what is a universe?":
- **S29** — *Identity*: a universe is a first-class entity with its own ID and boundary.
- **S33** — *Persistence*: a versioned envelope mechanism for storing universe state.
- **S39** — *Composition*: the content vocabulary (themes, tropes, archetypes) that fills a universe.

S33 persists what S39 defines. The composition schema (S39) is independent of
the persistence mechanism (S33) by design, so S39 can evolve without schema
migration and S33 can host other content shapes later.

| ID | Name | One-paragraph summary |
|---|---|---|
| **S39** | Universe Composition Model | The schema for "what is a universe?" — themes × tropes × archetypes × genre-twists. Composable, seedable, deterministic given (seed, config). The primitive that makes "parallel universes" concrete. Foundation for Scenario Seed Library (S41) and Resonance (S56 in v4+). |
| **S40** | Genesis v2 — Real→Strange | Supersedes v1 S02. Promotes the old-TTA narrator-arc design: Void → Building World → Slip → Building Character → First Light → Becoming → Threshold. The narrator is a shapeless void entity that progressively takes in-world form, becoming the player's guide. Closes v1 S02's deferred AC-2.3 (first turn references Genesis by name). **Structural relationship to v1 S02**: S40 expands v1 S02's 5 acts into 7 narrator-arc phases. v1 S02 remains closed with its 5-act normative content preserved as historical record; S40 is a new spec that replaces v1 S02's role in the live system at v2.0 release. |

**Dependencies**: S39 → S29. S40 → S29, S39, supersedes v1 S02.

---

## 4. v2.1 — "Prove It's Fun" (5 specs)

Validation infrastructure + curated content. The v1 charter's "What v2 Must
Address" #4 called for *both* automated simulation harnesses *and* real human
playtesters — the roadmap honors that distinction with separate specs.

### 4.1 Scenario Seed Library (S41)

| ID | Name | One-paragraph summary |
|---|---|---|
| **S41** | Scenario Seed Library | Curated, composable bundles of themes, tropes, archetypes, and genre-twists — the content that feeds S39 Universe Composition. Includes official/internal world templates (e.g., "Dirty Frodo" = LOTR + hardboiled-detective + urban-noir-prose). **Forward-pointer for spec author**: the old-TTA GDD's "strange mundane" onboarding scenarios (bus-stop shimmer, café-with-strange-symbols, library-with-forbidden-book) are canonical seeds — include them in the initial library. **User-generated templates are out of scope — see S63 Community.** Format, discovery, and metadata rules. |

**Dependencies**: S41 → S39.

### 4.2 Playtester Tooling (S42–S45)

| ID | Name | One-paragraph summary |
|---|---|---|
| **S42** | LLM Playtester Agent Harness | LLM-persona agents with semi-randomized taste profiles. Each agent plays a session end-to-end; produces a transcript + agent-side commentary. Persona definitions, taste-profile dimensions, scenario-selection logic. Automated, scalable, cheap — satisfies the *necessary* half of v2 validation. |
| **S43** | Human Playtester Program | Real humans play curated scenarios and surface UX and narrative gaps that LLM agents miss (emotional resonance, pacing fatigue, confusion points, moments of wonder). Recruitment process, consent and compensation policy, feedback-intake format, triage pipeline, regression-ticket process. Satisfies the *sufficient* half of v2 validation that the charter explicitly called out. Small-scale by design — 10–30 playtesters for v2.1 launch. |
| **S44** | Narrative Quality Evaluation | How a generated or played-through narrative is scored. Categories (coherence, tension, wonder, character depth, genre fidelity, consequence weight) and how each is computed — some automatically from transcripts (S42 input), some derived from human feedback (S43 input). Scoring rubric lives as **Appendix A** of this spec. |
| **S45** | Evaluation Pipeline | Orchestration: parallel LLM-playtester runs, human-playtester dashboard intake, result aggregation across both sources, CI integration, regression detection. Where results land (dashboard, CSV, Langfuse). Thresholds that fail a build. |

**Dependencies**: S42 → v1 S07, S41. S43 → S41. S44 → S42, S43. S45 → S42, S43, S44.

---

## 5. v3 — "Ship It" (4 specs + 1 extension)

Directly promotes the v1 charter's "What v2 Must Address" infrastructure list.
No new product surface; makes v2.0/2.1 reach real users reliably.

**Clarifying note on the charter's "single FastAPI process, no microservices"
mandate.** v3 preserves this constraint *per-instance*: each running instance
is a single FastAPI process with no microservice decomposition. Horizontal
scaling (S49) runs multiple copies of the same process behind a load balancer.
This is not a microservice architecture and does not violate §10 Scope Fences.

| ID | Name | One-paragraph summary |
|---|---|---|
| **S46** | Cloud Deployment Target | Concrete target (Fly.io vs Cloud Run vs other — decision in this spec), env parity across dev/staging/prod, secret management, zero-downtime deploys. **Extends v1 S14's local-only deployment scope to cloud targets. v1 S14 remains closed unchanged; S46 is a new spec that supersedes S14's role in the live system at v3 release.** |
| **S47** | Live Neo4j in CI | Ephemeral Neo4j per test run; replace the mocked integration tests flagged in v1 closeout. Test-data fixtures and setup/teardown cost. |
| **S48** | Async Job Runner | Job queue + worker for GDPR deletion, retention sweeps, backfills. The request-path handling of these today is the v1 gap. Picks a minimal job runner; a worker process is permitted alongside the FastAPI process within a single deployment unit — not a microservice. |
| **S49** | Horizontal Scaling & Multi-Instance Sessions | Multi-instance session storage; decision between session affinity and stateless sessions. Redis session store migration. Operates per-instance per the single-process clause above. |

**v1 S15 extension (no new spec)**: Add ACs requiring every alert to carry a
runbook-link field. Ship actual runbooks as `docs/runbooks/*.md`.

**Dependencies**: S46 → v1 S14. S47 → v1 S13, v1 S16. S48 → v1 S17, v1 S26. S49 → v1 S11, v1 S12.

---

## 6. v4+ — "Multiverse Unlock" (10 specs)

Promotes the real multiverse mechanics from the old TTA design docs (GDD
§Multiverse). Depends on v2.0's forward-compat architecture (S29–S33).
Dependency-ordered in three waves plus a parallel multiplayer track.

### 6.1 Wave A — Multi-universe Infrastructure

| ID | Name | One-paragraph summary | Depends on |
|---|---|---|---|
| **S50** | Concurrent Universe Loading | Two or more universes resident in memory simultaneously, each with its own persisted state (S33) and identity (S29). Resource-budget rules (how many is too many), eviction policy, isolation guarantees. Load-bearing prerequisite for every other v4+ feature. | S29, S33 |
| **S51** | Cross-Universe Travel Protocol | The mechanic by which an actor moves from Universe A to Universe B. Trigger conditions (portal, ritual, narrative hook), character-state transfer rules (what persists, what resets, what translates), arrival onboarding in the new universe. | S31, S50 |

### 6.2 Wave B — Nexus

| ID | Name | One-paragraph summary | Depends on |
|---|---|---|---|
| **S52** | Nexus as Special Universe | The Nexus is modeled as a universe whose composition (S39) permits inhabitants from any other universe. No engine-level "hub" special case — it's a universe with distinctive rules. Architecture, inhabitants, default content. | S50, S51 |
| **S53** | Nexus Access Rules | How and when players reach the Nexus: narrative triggers, gating, in-world explanation. The *story* of why players find Nexus, separate from its *mechanics* (S52). | S52 |

### 6.3 Wave C — Inter-Universe Dynamics

| ID | Name | One-paragraph summary | Depends on |
|---|---|---|---|
| **S54** | Inter-Universe Event Substrate | A communication bus between loaded universes. Pure primitive — no semantics. Events published in Universe A are available for subscription in Universe B. Delivery guarantees, ordering, rate limits. | S50 |
| **S55** | Bleedthrough Propagation Rules | The *semantics* of subtle inter-universe influence riding on S54. Weather anomalies, rumors of travelers, echoes of distant events. Probabilistic distortion rules as events cross the substrate. | S54 |
| **S56** | Resonance Correlation Engine | Thematic echoes: a choice made in Universe A subtly biases narrative weight in Universe B along shared themes or archetypes (per S39's vocabulary). Correlation rules, strength decay, author-intent controls. | S54, S39 |

### 6.4 Parallel Track — Multiplayer

| ID | Name | One-paragraph summary | Depends on |
|---|---|---|---|
| **S57** | Multi-Actor Universe Model | Multiple actors coexist in one universe. Promotes v1 S21 from future stub to full spec. Shared world-state semantics, per-actor narrative perspective rules. | S30, S31 |
| **S58** | Turn Conflict Resolution | What happens when two actors act simultaneously or contradictorily. Ordering rules, priority, narrative reconciliation. | S57, v1 S08 |
| **S59** | Multiplayer Transport | WebSocket implementation of the `NarrativeTransport` interface defined in S32. Session-level sync, presence, reconnection. Library choice decided here. | S32, S57 |

---

## 7. v5+ — "Long Vision" (4 specs, promote stubs)

v1 stubs S18–S22 are boundary documents that constrain v1 design. In v5+ four
of them are promoted to full functional specs. v1 S21 is **not** in this list;
it has been promoted into v4+ as S57/S58/S59 because multiplayer is tightly
coupled to multiverse infrastructure.

| ID | Promotes | One-paragraph summary |
|---|---|---|
| **S60** | v1 S19 Crisis Safety | **Gate** for S61 — must ship before therapeutic content is enabled. Crisis detection runtime, escalation pathways, clinician-notification rules, break-the-glass overrides. Defines the safety-first invariants that therapeutic content cannot bypass. |
| **S61** | v1 S18 Therapeutic Framework | MVP subset of the old-TTA design's 8 frameworks: **CBT + Mindfulness** narrative integration only. Therapeutic annotation layer consumes the S08 annotation hook added in v2.0. Clinical-mode UI toggle (from old-TTA GDD) scoped here. Future additions (DBT, ACT, Trauma-Informed, MI, SFBT, Narrative) deferred to v5+ continuation. |
| **S62** | v1 S20 Story Sharing | Export formats (PDF, ePub, web link), consent model per v1 S11, public story library, attribution. Uses S37's structured attributed memory as the export source — not raw transcripts. |
| **S63** | v1 S22 Community | User-generated world templates, moderation pipeline, attribution and licensing. Depends on S41 for engine primitives. The user-generated half of what S41 deliberately excludes. |

---

## 8. Forward-Compat ACs on v1 Specs

Rather than creating separate "groundwork specs" (which would design for
hypothetical futures — forbidden by `CLAUDE.md`), each v2.0 spec carries
explicit forward-compat acceptance criteria where the cost is near-zero.
Extensions to already-closed v1 specs are listed here; they are made as
non-normative addendums, not modifications to v1 ACs.

| v1 spec | Forward-compat AC (added in v2.0) | Serves | Source |
|---|---|---|---|
| **S04 World Model** | All actor-scoped references accept `actor_id: str` (single-valued in v2, list-valued in v4+). No hardcoded "player" references remain in the world model. | S57 Multi-Actor Universe Model | v1 S21 constraint 1 (⚠️ partial in v1) |
| **S08 Turn Pipeline** | Pipeline stages are parameterized on `actor_id`. `player_input` becomes a deprecated alias for `actor_input`. Stage contracts document the parameter. | S57/S58/S59 Multiplayer | v1 S21 constraint 3 (⚠️ partial in v1) |
| **S08 Turn Pipeline** | Post-turn annotation hook accepting arbitrary labelers. | S61 Therapeutic annotations | v5+ prep |
| **S10 API & Streaming** | Narrative delivery implements `NarrativeTransport` interface from S32. | S59 WebSocket multiplayer | v1 S21 constraint 4 (❌ unmet in v1) |
| **S15 Observability** | *(v3 extension)* Every alert carries a runbook-link field. | Ops runbooks | — |

These v1 extensions are AC additions delivered as part of the v2.0 / v3 release
streams — they are not new specs and do not modify v1 closed content.

**v1 S21 constraint coverage summary:**

| S21 constraint | v1 status | v2.0 forward-compat handling |
|---|---|---|
| 1. Multi-actor world model | ⚠️ Partial | ✅ S04 AC added (this table, row 1) |
| 2. Session ≠ world | ✅ Fulfilled | S30 completes separation |
| 3. Turn pipeline extensibility | ⚠️ Partial | ✅ S08 AC added (this table, row 2) |
| 4. SSE→WS migration path | ❌ Not fulfilled | ✅ S32 + S10 AC address this |
| 5. Character identity separation | ✅ Fulfilled | — |
| 6. Concurrent state mutation | ✅ Fulfilled | — |

All six S21 constraints are now addressed in v2.0 — either already fulfilled in
v1 or covered by a v2.0 forward-compat AC.

---

## 9. Spec-Drafting Order

Specs should be drafted in dependency order so each brainstorm has its
prerequisites locked. Proposed draft sequence:

1. **S29** (Universe as First-Class Entity) — unlocks everything else
2. **S30, S31, S33** (Session binding, Actor portability, Universe persistence) — parallelizable
3. **S32** (Transport abstraction) — independent, can go anytime
4. **S34** (Diegetic Time) — unlocks S35/S36/S37
5. **S35, S36, S37, S38** (Simulation pillars) — mostly parallelizable after S34
6. **S39** (Composition) — independent; feeds S40 and v2.1
7. **S40** (Genesis v2) — depends on S39
8. **v2.1 specs S41–S45** — after S39 locks composition vocabulary
9. **v3 specs S46–S49** — independent from v2; can start alongside v2.0
10. **v4+ and v5+** — defer drafting until the prior release ships

Each spec gets its own brainstorm session following the same skill workflow
that produced this document.

---

## 10. Open Questions (Resolved per Spec)

The following questions are surfaced here as a reminder; each is resolved
during the individual spec's brainstorm, not here.

| Spec | Question |
|---|---|
| S30 | 1:1 session↔universe policy — DB constraint or app-level? |
| S31 | What persists cross-universe (name? memory? stats?) — defer concrete answer to S51 |
| S33 | Schema version cadence — tied to release version or independent? |
| S34 | Diegetic-time-to-real-time mapping: configurable per universe or global? |
| S35 | NPC autonomy computation — batched LLM call with salience-filtered NPCs, or rule-based fallbacks? |
| S36 | Propagation graph depth limit — fixed or adaptive? |
| S37 | Memory compression threshold — token count or semantic boundary? |
| S38 | NPC memory shared across sessions in multiplayer (v4+) — one NPC remembers multiple players |
| S39 | Universe deterministic given (seed, config)? — probably yes, for playtester reproducibility |
| S40 | Minimum-viable WorldSeed field set — hard-gate or soft-prompt to continue? |
| S41 | Scenario format — YAML, JSON, TOML? Discovery — filesystem or registry? |
| S42 | LLM playtester persona count and taste-profile dimensions |
| S43 | Human playtester recruitment channels, compensation level, NDA/consent form |
| S44 | Scoring normalized 0–1 or categorical? Inter-rater reliability across LLM runs? Weighting LLM vs human signal? |
| S45 | Results destination — dashboard, CSV, Langfuse? |
| S46 | Cloud target — Fly.io vs Cloud Run vs other |
| S49 | Session affinity vs stateless sessions |
| S59 | WebSocket library choice |

---

## 11. What Changes in This Repo

Assuming this roadmap is approved:

1. **`specs/README.md`** — ✅ Done. "Reserved" block listing S29–S63 with release assignments added.
2. **`specs/00-project-charter.md`** — ✅ Done. Roadmap pointer block appended below the v1 Closeout section. v1 Closeout content remains frozen.
3. **`plans/index.md`** — No changes yet. Each release gets its own plan document after its specs are drafted.
4. **`specs/future/` stubs** — No changes yet. S18/S19/S20/S22 stay as stubs until v5+ begins.
5. **This document** — Lives at `docs/superpowers/specs/2026-04-21-v2-v3-roadmap-design.md` as the planning artifact.

Individual spec drafting, plan drafting, and GitHub issue creation happen
downstream of this document's approval.

---

## 12. Out of Scope for This Document

- Individual spec content (ACs, FRs, edge cases) — those are drafted per-spec.
- Plan content (architecture, stack decisions) — drafted after specs per SDD workflow.
- GitHub issue/task decomposition — generated after specs and plans exist.
- v2.0 / v2.1 / v3 target dates — not committed here. Dependency order is the plan; calendar is not.
- Staffing or resourcing.
- Any modification to v1 normative content. v1 is closed.
