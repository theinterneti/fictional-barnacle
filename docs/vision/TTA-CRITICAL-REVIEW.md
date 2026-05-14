# Critical Review: TTA Unified Vision & Roadmap

**Status**: Living stress-test — updated as concerns are resolved or new ones found
**Companion to**: TTA-UNIFIED-VISION.md
**Last updated**: 2026-05-13

---

## RESOLVED Concerns

These were challenged, discussed, and resolved — documented here for reference.

### Differentiator Risk ✓

**Challenge**: If v3 ships as "good interactive fiction, nothing special," does
anyone care enough to support v4/v5?

**Resolution**: TTA occupies empty space. Very few narrative IF games exist, none
attempt narrative therapy integration. The therapeutic vision, even deferred to
v5, is the differentiator. The project doesn't compete on "best IF" — it competes
on "only therapeutic narrative game."

### Human Playtester Availability ✓

**Challenge**: Who are the playtesters? Solo dev, no org, no budget.

**Resolution**: Build something engaging first, then share. Reddit, Discord,
IF communities — playtesters appear when there's something worth testing. The
constraint isn't recruitment, it's having something worth recruiting FOR. This
is a v2.1 problem, not a v2.0 problem.

### Emergent Behavior Evaluation ✓

**Challenge**: SDD can't spec emergent behavior. How do we know v2.0's simulation
feels alive?

**Resolution**: Simulated playtesters (LLM-persona agents in v2.1) ARE the
discovery mechanism. We can task them to try anything — break the world, test
edge cases, roleplay specific scenarios. The quality evaluation pipeline watches
turn transcripts for coherence, engagement, and "aliveness" signals. This is
exactly what v2.1 is for. The gap between "specs pass" and "feels good" is
closed by automated playtesting, not by better specs.

**Implication**: v2.1's simulated playtester harness becomes more important, not
less. It's not just a quality gate — it's our primary mechanism for discovering
whether the simulation works.

---

## ACTIVE Concerns

These remain open and need architectural attention.

---

## 1. FMR Tier Exhaustion Risk

**Status**: ACKNOWLEDGED — not fatal, but needs design

### Reality

Aggregate free model capacity across provisioned providers (Google, Groq, NVIDIA,
OpenRouter) is more than we can consume. The risk isn't total exhaustion — it's
exhausting specific model tiers:
- **Smart models** (Gemini Flash, Groq Llama-4): needed for narrative generation,
  quality evaluation
- **Fast models** (Gemini Flash-Lite, Groq Qwen-3): needed for low-latency tasks,
  input understanding

### What Happens Under Load

- 3+ concurrent playtester sessions all hitting the same Google Flash model →
  RPM cap, cooldowns, cascading 503s
- Background NPC autonomy (50+ NPCs updating) competes with player-facing calls
  for the same smart model pool
- The system degrades unpredictably — which calls fail depends on cooldown timing

### Required Design

A rate-limit budget that:
- Assigns RPM allocations per task type (player-facing > playtester > background)
- Degrades gracefully: background NPC updates slow down before player turns get slow
- Tracks per-provider utilization and shifts work to underutilized providers
- Works with FMR's `model:auto` (let FMR pick, but express priority constraints)

**Recommendation**: Add a "Rate Limit Architecture" section to the v2.1 component
plan. Not a full spec yet — just enough design to prevent v2.1's parallel
playtesting from starving player-facing calls.

---

## 2. Dukat Ideas Are Completely Unproven

**Status**: CONFIRMED — stronger than initial review

### Reality

Dukat was never built. Not a single line of implementation. Every concept —
Radiant Heart/Shadow Self, TLC Monk Council, Decision Matrix, Heroes Need
Healing framework — is pure design speculation with:
- Zero implementation evidence
- Zero player feedback
- Zero validation against real narrative interaction

### The Risk

When we reach v5 (years from now), Dukat's ideas may be:
- **Wrong**: Players don't experience Radiant/Shadow the way the design imagined
- **Obsolete**: LLMs evolved past the need for TLC Monk oversight; therapeutic
  game design matured in different directions
- **Incompatible**: Designed for a Neo4j-centric, LangGraph-era architecture that
  fictional-barnacle intentionally avoided

### The Discipline

Dukat is a **reference design**, not a feature catalog. When v5 planning begins:
1. Do fresh design work informed by v1-v4 learnings
2. Treat Dukat as one input among many, not a blueprint
3. Test every Dukat-derived concept against: does this still make sense with
   current LLMs, current architecture, and what we've learned from real players?

**Recommendation**: In the vision document, Dukat ideas are now explicitly labeled
as "theoretical, unproven — reference only." No Dukat-derived feature gets
scheduled without fresh validation.

---

## 3. Content Richness vs. Latency Budget

**Status**: ACTIVE — needs design constraint

### The Tension

FMR enables richer generation. But richer = more tokens = more latency. The
latency budget is real: TTA's game creation already pushes past 30s with just
2 LLM calls. Content richness means MORE calls and LARGER calls.

### Two Kinds of Richness

**World-state richness** (generate detailed locations, NPCs, factions ONCE at
Genesis time, reference thereafter) — pays for itself. One expensive generation,
cheap reads forever.

**Response richness** (every turn generates flowery prose, deep descriptions,
elaborate narration) — costs compound. Every turn is more expensive than the
last version.

### The Design Question

Should v2.1's content richness track focus on world-state depth (one-time cost)
or response depth (per-turn cost)? The vision currently conflates both.

**Recommendation**: Split the content richness track:
- **Richness-at-rest**: Procedural locations, items, factions, world detail —
  generated at Genesis time or on first visit. Stored in Neo4j. One-time LLM cost.
- **Richness-in-flight**: Per-turn narrative quality — tone calibration, pacing,
  callbacks. These cost LLM tokens every turn. Budget them carefully.

Define a latency budget per turn type (standard: 5-8s, complex: 12-15s, genesis:
30-45s) and fit richness-in-flight within it.

---

## 4. Single-Process Concurrency Ceiling

**Status**: ACTIVE — unknown, needs measurement

### The Question

At what concurrency does the single FastAPI process degrade? v2.1 runs parallel
playtester sessions. v3 runs multiple human players.

### What We Don't Know

- Python GIL contention under concurrent LLM client calls
- Neo4j driver connection pool limits under parallel graph queries
- Memory per active session (world state, context, history)
- SSE connection overhead per player

### Why This Matters

v3's horizontal scaling design depends on knowing when single-process breaks.
If we guess wrong, v3's architecture is built on wrong assumptions.

**Recommendation**: Add a "concurrency stress test" to v2.1 — run N parallel
playtester sessions and measure latency, memory, and error rates as N increases.
Find the ceiling empirically before designing v3.

---

## 5. Genesis Quality Gate

**Status**: ACTIVE — needs v2.0 merge gate

### The Problem

Genesis v2 (7-phase Real→Strange arc) ships in v2.0. World quality is evaluated
in v2.1. If Genesis produces bad worlds, v2.0 ships with a broken foundation.

### What We Need

A lightweight smoke test before merging v2.0:
- Run Genesis v2 N times (N=20 minimum)
- Manually evaluate a sample (5 worlds)
- Verify: basic coherence, location diversity, NPC distinctiveness
- Gate: X% of generated worlds must be "playable" (TBD threshold)

### Not the Full Quality Pipeline

This isn't v2.1's automated evaluation. It's a manual check to prevent shipping
a Genesis that generates incoherent worlds. 30 minutes of human review, not a
multi-day test harness.

**Recommendation**: Add Genesis smoke-testing to the v2.0 merge checklist.
Define "minimum playable world" criteria. Do it before merge, not after.

---

## 6. Architecture Inertia

**Status**: ACTIVE — review after v2.0 stabilizes

### The Pattern

v1's architecture choices (single FastAPI, LiteLLM library mode, Neo4j CE,
SSE streaming) made sense for v1. Each version inherits them. Changing them
gets harder as the codebase grows.

### What Might Be Wrong for v3+

- **LiteLLM library mode**: We're using LiteLLM to call FMR's HTTP API. Is
  this the right layering, or should we call FMR directly?
- **Neo4j CE**: Consequence propagation and content richness increase graph
  query volume. CE's no-parallel-queries limit may arrive faster than expected.
- **SSE for multi-player**: Works for one player. For N players, N SSE
  connections × keepalives × reconnection logic.

### The Discipline

After v2.0 stabilizes, before designing v2.1's implementation:
- Audit every v1 architectural choice
- Ask: "If we started today, would we choose this?"
- Identify the choices we'd change and decide: change now, or defer to v3?

**Recommendation**: Add an "Architecture Review" gate between v2.0 merge and
v2.1 design. One document, one decision per choice, no ambiguity.

---

## 7. The Web Client Gap

**Status**: ACTIVE — not in the roadmap

### The Problem

The vision never mentions the player-facing interface. v1 has a minimal HTML/JS
page. v2.0 adds transport abstraction but no UI. At some point (v3? v4?),
"terminal text box" stops being acceptable.

### What Players Expect

By the time v3 ships (2027+), players expect at minimum:
- Styled text output (not raw monospace)
- Choice buttons alongside free-text input
- Character sheet / inventory view
- World map / location browser
- Dark fantasy aesthetic (thematic UI)

### Where Does This Go?

If UI is deferred too long, the game is unplayable even if the simulation is
great. If UI is prioritized, it competes with simulation depth.

**Recommendation**: Add a UI track to the roadmap — not as a separate version,
but as a parallel concern per version:
- v2.0: Minimal (current HTML/JS page) — acceptable for dev/testing
- v2.1: Basic styled output, choice buttons — acceptable for playtesters
- v3: Character sheet, world map, dark theme — acceptable for public players
- v4+: Voice, accessibility, mobile — nice to have

---

## 8. Richness Scope Creep Risk

**Status**: ACTIVE — needs a budget

### The Risk

"Content richness" has no natural endpoint. Every location can be more detailed.
Every quest can be more dynamic. Every faction web can be deeper. Without a
budget, v2.1's richness track becomes a project-in-a-project.

### The Fix

Define a **richness budget** for v2.1:
- X location templates with Y+ properties each
- Z quest archetypes with dynamic parameters
- Faction web with at least N relationships per faction
- Tone calibration covering 3+ narrative modes (action, exploration, dialogue)

When the budget is met, richness is done. Move on to v3.

**Recommendation**: Add concrete richness targets to the v2.1 component plan.
Numbers, not adjectives. "Done" is defined by meeting the budget, not by feeling
"rich enough."

---

## Open Questions (unresolved)

1. **Minimum differentiator timing**: If therapeutic integration is v5, what
   makes v3 distinctive? Is "deep simulation IF" enough? Adam says yes — the
   space is empty. Worth revisiting if competitive landscape changes.

2. **Clinical review for v5**: Even at the end of the roadmap, who validates
   the therapeutic framework? This gates v5 deployment. No answer yet, and
   no urgency to find one until v4 is in sight.

3. **Decision matrix spike**: Dukat's 4-factor decision matrix (Narrative ×
   World × Character × Randomness) might improve narrative quality without
   being therapeutic. Worth a small experiment? Recommendation: spike it in
   a throwaway branch — if it measurably improves quality, extract for v2.1.
   If not, leave with Dukat.

---

## Summary: What Changed

| Concern | Initial | After Review |
|---------|---------|-------------|
| FMR "unlimited" | False | Effectively unlimited aggregate, constrained smart/fast tiers |
| Dukat proven | Overstated | Confirmed: completely unproven, theoretical only |
| Emergent behavior | Can't spec | Resolved: simulated playtesters are the discovery mechanism |
| Differentiator | Risk of "just IF" | Resolved: empty space, therapeutic vision is the differentiator |
| Human playtesters | Who? | Resolved: build engaging → share → playtesters come |
| Content richness vs latency | Undifferentiated | Split: richness-at-rest vs richness-in-flight, latency budgets |
| Genesis quality gate | Missing | Added: smoke test before v2.0 merge |
| Architecture inertia | Unacknowledged | Added: architecture review gate after v2.0 |
| Web client | Missing | Added: UI track per version |
| Richness scope creep | Unbounded | Added: concrete richness budget |
