# TTA Strategy & Planning

**Status**: Companion to [TTA Unified Vision & Roadmap](./TTA-UNIFIED-VISION.md)
**Created**: 2026-05-13
**See also**: [Threads Reference](./TTA-THREADS.md)

---

Supporting strategic documents: feasibility explorations, dependency strategy,
go-to-market plan, lessons learned, open decisions, and edge cases.

## Features Requiring Feasibility Exploration

Some features are too complex or too unproven to schedule directly. They need
a **research phase** before graduating to the roadmap. The pattern is:

```
Research Spike → Feasibility Prototype → Scheduled Phase → Expansion
```

If the spike fails, the feature is rethought or dropped. If it succeeds, it
graduates to a scheduled phase and expands across subsequent versions.

### TLC Monks

**What it is**: AI personas based on historical/literary figures providing
narrative guidance, ethical oversight, and multi-perspective storytelling.

**Why it needs exploration**: Nobody has built this. We don't know if AI can
consistently embody a specific historical persona, whether multi-perspective
narration improves player experience, or whether players engage with the Monk
concept at all. This could easily be annoying rather than enriching.

**Note**: The TLC Monk concept was developed during a challenging period. When
we reach the exploration phase, re-evaluate with fresh perspective.

**Exploration path**:

| Stage | When | What |
|-------|------|------|
| **Research** | v2.1 era | Can a model consistently embody one historical persona across a full session? Run 20 sessions with a single Monk persona. Does the voice stay consistent? Does it add value? |
| **Prototype** | v3 era | Single Monk, opt-in. Players can toggle "Monk guidance" on/off. Measure: do they keep it on? Does narrative quality improve? |
| **Graduate?** | v3→v4 gate | If prototype succeeds: schedule full Council for v5. If it fails: drop or rethink. |
| **Council v1** | v5 | Multiple Monks, dynamic role allocation, ethical oversight of generated content. |
| **Council v2** | v5+ | Council governance with voting, player-customizable Monk roster, community-shared Monk personas. |

The critical question: **is a single Monk persona valuable?** If one Monk doesn't
improve the experience, a council of them certainly won't. Start with one.

### Decision Matrix

**What it is**: 4-factor weighted narrative generation (Narrative × World ×
Character × Randomness) replacing or augmenting the linear pipeline.

**Why it needs exploration**: It's an entirely different generation architecture.
We need to know if it produces measurably better narrative before committing to
a pipeline rewrite.

**Exploration path**:

| Stage | When | What |
|-------|------|------|
| **Spike** | v2.1 era | Throwaway branch. Generate 50 turns with current pipeline, 50 with decision matrix. Blind A/B compare. Does it win? |
| **Graduate?** | v2.1→v3 gate | If measurable improvement: schedule for v4 narrative engine. If not: drop. |
| **Implementation** | v4 | Replace or augment pipeline with decision matrix engine. |
| **Expansion** | v5 | Concept maps, emotional feedback loops, thematic resonance. |

### Cross-Universe Travel / Character Passport

**What it is**: Players take their character between universes hosted on different
instances. Requires character state serialization, universe compatibility
contracts, and a discovery mechanism.

**Why it needs exploration**: This is architecturally the most disruptive feature
in the roadmap. It requires universe-to-universe compatibility validation, safe
character state transfer, and P2P instance discovery — all unsolved problems.

**Exploration path**:

| Stage | When | What |
|-------|------|------|
| **Research** | v3 era | Design the character passport format. What state transfers? What doesn't? How do incompatible universes reject a character gracefully? |
| **Prototype** | v4 era | Two instances, one character. Transfer between them. Does the character arrive intact? Does the destination universe make narrative sense? |
| **Graduate?** | v4→v5 gate | If prototype works: schedule full cross-universe travel + central Nexus for v5. |
| **Travel v1** | v5 | Character passport between compatible universes. Basic compatibility validation. |
| **Travel v2** | v5+ | Central Nexus universe. Character routing. Cross-universe narrative resonance. |

### Genesis World Quality

**What it is**: Can Genesis v2 (7-phase Real→Strange arc) produce diverse,
compelling, playable worlds at scale?

**Why it needs exploration**: Genesis v2 is ambitious. We don't know the quality
distribution of generated worlds. If 70% are incoherent or repetitive, the
entire simulation thread is built on sand.

**Exploration path**:

| Stage | When | What |
|-------|------|------|
| **Smoke test** | v2.0 merge gate | Generate 20 worlds. Manually evaluate 5. Are they playable? Diverse? |
| **Automated eval** | v2.1 | Playtester agents run sessions in generated worlds. Quality scores per world. |
| **Graduate?** | v2.1→v3 gate | If quality distribution is acceptable: proceed. If not: Genesis needs redesign before v3. |
| **Community seeds** | v3 | Human-curated scenario seeds supplement procedural generation. |
| **Player-authored** | v5 | Players create and share worlds. |

### Therapeutic Narrative Integration

**What it is**: Can narrative therapy concepts (reflection opportunities, growth
arcs, emotional processing) work within interactive fiction, driven by free models?

**Why it needs exploration**: This is the core differentiator and the biggest
unknown. Dukat imagined it but never tested it. We need to know if free models
can surface therapeutic opportunities naturally, and how players respond —
before committing to v5's full therapeutic framework.

**Exploration path**:

| Stage | When | What |
|-------|------|------|
| **Research** | v4 era | Small experiment: 5 players, 10 sessions each. Manual analysis: do therapeutic moments emerge naturally? Can we prompt free models to create them without being heavy-handed? |
| **Prototype** | v4→v5 gate | Opt-in "reflection mode" — player can request a reflective pause after significant events. AI generates a reflection prompt. Measure: do players use it? Does it add value? |
| **Graduate?** | v4→v5 gate | If research and prototype show promise: schedule full therapeutic framework for v5. If not: rethink. |
| **Framework v1** | v5 | Healing opportunities, therapeutic annotation, consent framework. |
| **Framework v2** | v5+ | TLC Monk therapeutic guidance, clinical validation, efficacy research. |

The critical question: **do therapeutic moments feel natural in IF, or do they
break immersion?** If players recoil from "therapy in my game," the entire v5
vision needs rethinking. Better to learn this in v4 with a small experiment than
in v5 after building the framework.

---

## External Dependency Strategy

The stack starts intentionally minimal: FastAPI, LiteLLM (library mode), Neo4j
driver, SQLModel, Redis. Every external dependency is a bet — the question is
when to place it.

### Current Stack Rationale

| Dependency | Why We Use It | Why Not Something Else |
|-----------|---------------|----------------------|
| FastAPI | Async Python, native SSE, mature ecosystem | Not Flask (sync), not Django (too heavy) |
| LiteLLM | 100+ provider abstraction, streaming, fallback | Not direct OpenAI SDK (single-provider lock-in) |
| Neo4j driver | Direct Cypher, no ORM overhead | Not LangChain graph (abstraction we don't need) |
| SQLModel | Thin SQLAlchemy + Pydantic | Not raw asyncpg (lose model validation), not SQLAlchemy 2.0 ORM (heavier) |
| No LangChain | Linear pipeline doesn't need agent framework | We'd use it for agent orchestration, which v1-v2 don't need |
| No PydanticAI | Manual JSON parsing works for current LLM output structure | We'd adopt when structured output volume justifies it |
| No LangGraph | Pipeline is linear, not cyclic/resumable | We'd adopt if narrative engine becomes graph-shaped |

### When to Adopt a Major Dependency

Each of these is a candidate for future adoption. The question is when.

| Dependency | Trigger to Adopt | Earliest Version | Migration Risk |
|-----------|-----------------|-----------------|---------------|
| **PydanticAI** | LLM structured output becomes frequent and fragile. Manual JSON parsing breaks under model variance. | v3 | Low — drop-in for specific LLM call sites |
| **LangGraph** | Narrative engine becomes cyclic/resumable. NPC autonomy needs checkpointed workflows. Turn pipeline branches beyond linear. | v4 | High — replaces core pipeline architecture |
| **Celery / ARQ** | Background work (NPC autonomy, playtesting, world simulation) exceeds what in-process async can handle. | v3 | Medium — adds broker dependency (Redis already available) |
| **React / Svelte** | Web client needs component architecture, state management, routing. Current minimal HTML can't scale to character sheet + map + inventory. | v3 | Low — greenfield client, no migration needed |
| **WebRTC / WebSockets** | Multiplayer invite (v3) needs real-time communication. SSE is one-way. | v3 | Medium — replaces/augments SSE transport |

### Migration Strategy

When we adopt a major dependency, the pattern is:

1. **Spike in a throwaway branch** — prove the dependency solves the problem
   better than what we have
2. **Incremental adoption** — replace one call site, not the whole system
3. **Dual-run validation** — run old and new side-by-side, compare output
4. **Full migration** — only after validation
5. **Remove old code** — don't keep both paths

**Never**: big-bang rewrite. "We're switching to LangGraph" = a year of
regression. "We're using LangGraph for this one workflow" = a week of
experimentation.

### Anti-Patterns

- **Adopting a framework for future needs.** LangGraph is for cyclic/resumable
  workflows. Our pipeline is linear. Don't adopt it because "we might need it
  later." Adopt it when we need it.
- **Adopting a framework for one feature.** If only the NPC autonomy system needs
  LangGraph, don't rewrite the turn pipeline in LangGraph. Use it where needed.
- **Framework-as-architecture.** The framework should serve the architecture,
  not define it. If adopting LangGraph means changing how sessions work, how
  state flows, and how errors are handled — the tail is wagging the dog.

### Where These Decisions Live

Dependency evaluation is not a spec — it's an architecture review conducted
between versions, when the trigger condition is met. The decision lives in the
component plan for the version that adopts it (e.g., "v3 Adopts ARQ for Async
Jobs" would be a section in the v3 component plan).

---

## Go-to-Market & Public Presence

TTA is currently private — shared with a few trusted people, not public. The
repo, the app, and the vision are all in stealth. This is intentional and
correct for now, but the roadmap includes becoming public. That transition
needs planning, not improvisation.

### The Risks

- **Bad actors**: Public repo = anyone can clone, fork, or sabotage. Public
  app = anyone can attack, exploit, or abuse.
- **Viral attention before preparedness**: Nothing like TTA exists. If it
  catches attention, the influx of players, contributors, and scrutiny could
  overwhelm a solo developer.
- **Copycats**: The ideas in this vision document are novel. Once public,
  well-funded teams could execute faster.
- **Haters and toxicity**: Any public creative work attracts negativity.
  Therapeutic narrative games may attract targeted harassment.

### The Phased Approach

| Phase | When | What |
|-------|------|------|
| **Stealth** | v1-v2.0 (NOW) | Repo is private or access-controlled. Only trusted individuals know about it. Vision doc is internal. No public presence. |
| **Curated circle** | v2.1 | Invited playtesters only. NDA or trust-based confidentiality. Feedback gathered privately. Still no public repo or website. |
| **Waitlist launch** | v3 | Landing page with email signup. Accounts are invite-only or waitlisted. Repo remains private but app is accessible to approved players. Community guidelines published. Moderation tools in place. |
| **Public launch** | v4 | Repo goes public (if open-source is the decision). App is open to everyone. Community spaces (Discord, Reddit). Published roadmap. Contribution guidelines. Code of conduct. |
| **Mature community** | v5 | Self-sustaining community. Community moderators. Player-run events. Reputation systems. |

### Key Decisions (deferred, not decided)

- **Open source or source-available?** Public repo invites contribution but
  also invites copycats. Source-available (view, not fork) protects the vision
  but limits community contribution.
- **When to announce?** Too early = unprepared for attention. Too late =
  missed momentum. The waitlist launch (v3) is the natural announcement point
  — enough to show, not enough to overwhelm.
- **Moderation strategy**: Who moderates the community? Automated tools at
  v3, human moderators at v4, community moderators at v5.

### The Principle

**Don't go public until the game is worth defending.** If v3 is engaging
enough that players would be upset if it disappeared, that's the right
moment to open the doors. Not before.

---

## What We Learned From Dukat

**Critical caveat**: Dukat was never built. Every idea is pure design — zero
implementation, zero player feedback. **Theoretical concepts only.** When v5
planning begins, do fresh design. Dukat is a reference point, not a blueprint.

Key concepts for future reference:
- Radiant Heart/Shadow Self personality model (→ v4 personality depth)
- TLC Monk Council as narrative governance (→ v5 concept-driven narrative)
- Decision Matrix (→ v4 narrative engine)
- 70/30 tone calibration (→ v2.1 quality evaluation)
- Heroes Need Healing framework (→ v5 therapeutic)

---

## What We Learned From TTA.dev

TTA.dev has production-ready primitives we should use, not rewrite:

| Primitive | Use In | Purpose |
|-----------|--------|---------|
| RetryPrimitive | v2.0+ | LLM calls, Neo4j queries |
| FallbackPrimitive | Already in use | Multi-backend LLM routing |
| TimeoutPrimitive | v2.1+ | Playtester session timeouts |
| CachePrimitive | v2.1+ | Scenario seed caching, LLM response cache |
| CircuitBreakerPrimitive | v3+ | Production safety for external APIs |
| MemoryPrimitive | v2.1+ | Playtester agent conversational memory |
| ParallelPrimitive | v2.1+ | Concurrent playtester runs |

Recommendation: add `ttadev` as a dependency when we start v2.1. Start with
RetryPrimitive and CachePrimitive — lowest risk, highest immediate value.

---

## What We Learned From Old TTA

Old TTA's value is in its **production scars**, not its code:

1. **Safety hooks work.** The pre/post-generation hook pattern (interfaces in S24)
   is battle-tested. When we implement S24 for real (v3+), the old TTA's
   implementation patterns are reference material.

2. **Narrative beat tracking prevents drift.** Old TTA's pacing system caught
   tone shifts before players noticed. This informs v2.1's quality evaluation.

3. **Stream interruption is hard but essential.** The ability to halt mid-stream
   when safety hooks fire was a production requirement. Design for this in v2.0's
   transport abstraction, implement in v3.

---

## Open Decisions

1. **v2.1 scope**: Quality AND richness in one version, or sequential?
   Recommendation: both — quality needs rich content to evaluate.

2. **Decision Matrix spike**: Test Dukat's 4-factor approach in a throwaway
   branch. If measurable quality improvement, extract for v2.1.

3. **ttadev dependency**: Add in v2.1. Start with RetryPrimitive and
   CachePrimitive.

4. **v3 invite model**: How does "invite friends to your instance" work
   technically? WebRTC? Tailscale? Shared URL + auth? Needs architectural
   investigation before v3 design.

5. **P2P architecture**: What does the tracker look like? A DHT? A central
   registry? A universe itself? This is years out — direction matters more
   than detail.

6. **Open source or source-available?**: Deferred to v4 gate.

---

## Edge Cases & Open Concerns

These are cross-thread issues that don't fit a single thread but need design
attention before the relevant version ships.

| Concern | Hits Version | The Problem |
|---------|-------------|-------------|
| **Player abandonment** | v3+ | Player stops playing mid-session. Default: world freezes. Player-configurable real-time mode: world continues without them (great for simultaneous multiplayer). Which mode is the default? How is the choice surfaced? |
| **Griefing in multiplayer** | v3 | Invite-only private means trusted friends. But trust fails. What prevents a friend from destroying your universe? This needs its own research and design map — permissions, undo, world snapshots, guest vs owner capabilities. Not a feature, a safety architecture. |
| **Data retention & intelligent cleanup** | v3+ | Saves, scenes, characters, worlds accumulate. Need user/admin-configurable retention policies: auto-delete after N days, archive unused worlds, per-entity retention settings. GDPR deletion must propagate cleanly. |
| **GDPR across P2P** | v4-v5 | Player deletes account. Their data exists on self-host instances and P2P networks. How does deletion propagate? Who is the data controller for shared content? Inform-and-offer-choices pattern: players must know where their data lives and have options. |
| **System mismatch on import** | v4 | Player imports a character from a 5e universe into a Fate universe. The game systems are different. What converts? What's lost? |
| **Neo4j CE ceiling** | v3+ | When does Community Edition become the bottleneck? Consequence propagation + content richness + NPC autonomy all increase graph query volume. |
| **Single-process ceiling** | v2.1→v3 | At what concurrency do we outgrow single FastAPI? v2.1 stress-testing answers this, but the answer gates v3 architecture. |
| **Content moderation at scale** | v4 | Pattern filtering (v2.1) and sentiment monitoring (v3) work at small scale. Public launch means unknown players generating unknown content. |
| **Scene data format** | v2.1→v3 | What's the scene schema? Must be forward-compatible across versions. Must survive game system changes. Must be human-readable enough for community sharing. |
| **Voice ownership** | v5 | TLC Monks have distinct voices. If a player creates a Monk persona, who owns it? Can it be shared? What if it's inappropriate? |
