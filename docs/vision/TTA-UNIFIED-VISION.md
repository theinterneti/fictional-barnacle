# TTA Unified Vision & Roadmap

**Status**: Living document — matures as each version proves its layer
**Created**: 2026-05-13
**See also**: [Threads Reference](./TTA-THREADS.md) · [Strategy & Planning](./TTA-STRATEGY.md)

## Status Legend

| Icon | Meaning |
|------|---------|
| ✅ | Done — shipped and proven |
| 🔄 | Active — code complete, merging or in progress |
| 📋 | Planned — next up, specs exist |
| 🔮 | Stubbed — direction set, details deferred |
| 🌅 | Vision — compass heading, not scheduled |

---

## Vision Maturity Principle

This document is not a fixed blueprint. It is a **living roadmap** that expands
as we prove each layer. We don't design v5 from v1 — we design vNext based on
what we just learned and what we just unlocked. The full vision exists as a
**directional compass**, not a schedule.

Big ideas are not features that land in one version. They are **threads** that
weave through the entire roadmap — each thread has its own maturity arc spanning
multiple versions. The versions are defined by which phase of each thread they
include.

---

## Where We Are

### v1: The Spine ✅

**Status**: DONE (335/335 ACs, 2773 tests, 25/28 integration)
**Unlocked**: LLM + world graph produces coherent, streaming IF. Pipeline works.
Free models drive narrative. The architecture is proven.

### v2.0: Believable Simulation 🔄

**Status**: CODE COMPLETE, merging
**Unlocked** (once merged): Persistent universes, diegetic time, autonomous NPCs,
consequence propagation, world memory, NPC social models, Genesis v2.

### The Current Unlock: FMR

free-model-router delivers effectively unlimited free LLM capacity across
provisioned providers (Google, Groq, NVIDIA, OpenRouter free tiers). Individual
model tiers can be exhausted (smart models under heavy load, fast models under
concurrency), but aggregate capacity is more than we can consume.

**Rate-limit reality**: A rate limiter that prioritizes player-facing calls over
background work is needed before v2.1.

---

## Big Ideas: Threads Through Versions

Each thread is a capability that matures across the roadmap. Versions are defined
by which phases of each thread they include. Detailed descriptions live in the
[Threads Reference](./TTA-THREADS.md).

```
THREAD               v1        v2.0        v2.1        v3          v4          v5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Simulation    ────── ● ─────── ●●● ─────── ●●● ─────── ●●● ─────── ●●●● ────── ●●●●
                         universe    quality    production  multiverse  full
                         entities    eval       scale       depth       depth

Gameplay      ────── ●· ────── ●●· ────── ●●● ─────── ●●● ─────── ●●●● ───── ●●●●
                         free-text   context    structured  quest       decision  multi-
                         turns       enriched   turns       arcs        matrix    perspective

Game Systems  ────── ·· ────── ·· ─────── ●· ─────── ●●· ────── ●●● ────── ●●●●
                         (none)     (none)    world-      OSS        multi-     player-
                                              based       baseline   system     defined

Difficulty    ────── ·· ────── ·· ─────── ●· ─────── ●●· ────── ●●● ────── ●●●●
& Failure             (none)     (none)    narr-only   player     system-    adaptive
                                           no death    config     defined    difficulty

Progression   ────── ·· ────── ·· ─────── ●· ─────── ●●· ────── ●●● ────── ●●●●
                         (none)     (none)    milestone  achieve-   community  player-
                                              tracking   ments      badges     defined

Economy       ────── ·· ────── ·· ─────── ·· ─────── ●· ─────── ●●· ────── ●●●
                         (none)     (none)     (none)    static     dynamic   full
                                                        resources  trade     simulation

NPC Society   ────── ·· ────── ●· ─────── ●●· ────── ●●● ─────── ●●●· ───── ●●●●
                         (none)    basic      faction    emergent   cross-    player
                                   autonomy   dynamics   stories    universe  impact

Save/Load     ────── ●· ────── ●· ─────── ●●· ────── ●●● ─────── ●●● ────── ●●●●
                         manual     manual     auto-save  save       cross-    save
                         save       save       + slots    sharing    universe  editing

Maps/Travel   ────── ·· ────── ●· ─────── ●●· ────── ●●● ─────── ●●●· ───── ●●●●
                         (none)    spatial    routes +   interactive cross-    dynamic
                                   relations  distances  map+fog     universe  discovery

Image Gen     ────── ·· ────── ·· ─────── ●· ─────── ●●· ────── ●●● ────── ●●●●
                         (none)     (none)    basic      scene      style-    player-
                                              portraits   illus      consistent customizable

Multiplayer   ────── · ─────── ·· ─────── ·· ─────── ●· ─────── ●●● ────── ●●●●
                         (none)     (none)     (none)    invite     p2p share  central
                                                        private    public     nexus

Worlds/Content ────── ● ─────── ●●● ─────── ●●●● ────── ●●●● ────── ●●●● ───── ●●●●
                         genesis    genesis    procedural community  universe  player
                         lite       v2         depth      seeds      templates authored

Genesis/     ────── ●· ────── ●●● ─────── ●●● ─────── ●●● ─────── ●●●· ───── ●●●●
Onboarding            lite       v2         adaptive   guided     collab-   multi-
                                  7-phase     returning  TLC Monk   orative   world

Quality       ────── · ─────── ·· ─────── ●●● ─────── ●●● ─────── ●●● ────── ●●●
                         (none)     (none)    automated  human      continuous prod
                                              playtest   validation monitoring

Therapeutic   ────── · ─────── ·· ─────── ·· ─────── ·· ─────── ●· ────── ●●●●
                         (none)     (none)     (none)    (none)    personality healing
                                                                  depth only framework

Context Eng   ────── ●· ────── ●●· ────── ●●● ─────── ●●● ─────── ●●●● ───── ●●●●
                         fixed      per-agent  agent      dynamic    cross-     self-
                         window     templates  comms      context    agent      optimizing

Safety        ────── ·· ────── ·· ─────── ●· ─────── ●●· ────── ●●· ────── ●●●●
                         stub       stub      pattern    sentiment  crisis     full
                         interfaces           filter     monitor    detection  consent

Narrative     ────── ●· ────── ●●· ────── ●●● ─────── ●●● ─────── ●●●● ───── ●●●●
                         linear     context   quality    beat       decision   multi-
                         pipeline   enrich    eval       tracking   matrix     perspective

Concepts      ────── ·· ────── ·· ─────── ●· ─────── ●●· ────── ●●● ────── ●●●●
                         (none)     (none)    tone       concept    thematic   steering
                                              tags       maps       resonance  creation

Prompt Eng    ────── ●· ────── ●●· ────── ●●● ─────── ●●● ─────── ●●●● ───── ●●●●
                         static     template  versioned  meta-      prompt     self-
                         prompts    injection in LF      prompts    chains     improving

UI/Client     ────── ●· ────── ●· ─────── ●· ─────── ●●● ─────── ●●● ────── ●●●●
                         minimal    minimal   styled     character  voice      full
                         html       html      output     sheet+map  access     client

Player Exp    ────── ·· ────── ·· ─────── ●· ─────── ●●· ────── ●●● ────── ●●●●
                         dev        dev       playtester accounts   public    mature
                         terminal   terminal  invite     + hosted   launch    platform

Infra         ────── ●· ────── ●· ─────── ●· ─────── ●●● ─────── ●●●● ───── ●●●●
                         docker     docker    concurrency fly.io     self-host p2p
                         compose    compose   stress      deploy     instances tracker

Sharing       ────── · ─────── ·· ─────── ·· ─────── ●· ─────── ●●· ────── ●●●
                         (none)     (none)     (none)    story      character community
                                                        export     passport  templates

Scenes        ────── ·· ────── ·· ─────── ●· ─────── ●●· ────── ●●● ────── ●●●●
                         (none)     (none)    scene      scene      scene     scene
                                              tracking   export     import    library

SPECABILITY   ────── ✓✓ ────── ✓✓ ─────── ✓✓ ─────── ✓⚠ ─────── ⚠⚠ ────── ⟳⟳
                         specable   specable   specable   mixed      directional stubs
```

**Legend**:  ·  not present   ●·  stub/minimal   ●●  basic   ●●●  mature   ●●●●  full
**Specability**:  ✓✓ = specable (testable ACs)   ✓⚠ = mixed   ⚠⚠ = mostly directional   ⟳⟳ = boundary stubs only

---

## Version Summary

### v1: The Spine ✅
Simulation: Linear world. Gameplay: Free-text turns. Game Systems: None.
Difficulty: None. Progression: None.
Economy: None. NPC Society: None. Save/Load: Manual save. Maps/Travel: None. Image Gen: None.
Multiplayer: Solo. Genesis: Genesis-lite. Worlds: Template worlds. Quality: Manual.
Therapeutic: None. Context Eng: Fixed window. Safety: Stub interfaces.
Narrative: Linear pipeline. Concepts: None. Prompt Eng: Static prompts.
UI: Minimal HTML. Player Exp: Dev terminal. Infra: Docker compose. Sharing: None. Scenes: None.

### v2.0: Believable Simulation 🔄
Simulation: Persistent universe. Gameplay: Context-enriched turns. Game Systems: None.
Difficulty: None. Progression: None.
Economy: None. NPC Society: Basic autonomy. Save/Load: Manual save. Maps/Travel: Spatial relations. Image Gen: None.
Multiplayer: Solo. Genesis: Genesis v2. Worlds: Deep worlds. Quality: Manual.
Therapeutic: None. Context Eng: Per-agent templates. Safety: Stub interfaces.
Narrative: Context-enriched. Concepts: None. Prompt Eng: Templated injection.
UI: Minimal HTML. Player Exp: Dev terminal. Infra: Docker compose. Sharing: None. Scenes: None.

**Gates for v2.1**: v2.0 merged to main. Integration tests pass with FMR. Genesis v2
produces playable worlds. NPC autonomy produces observable world changes. Consequence
propagation works at depth 2+.

### v2.1: Quality & Depth 📋
Simulation: Quality-validated. Gameplay: Structured turns. Game Systems: World-based.
Difficulty: Narrative-only. Progression: Milestone tracking.
Economy: None. NPC Society: Faction dynamics. Save/Load: Auto-save + slots. Maps/Travel: Routes + distances. Image Gen: Basic portraits.
Multiplayer: Solo. Genesis: Genesis v2. Worlds: Procedural depth. Quality: Automated playtesting.
Therapeutic: None. Context Eng: Agent comms. Safety: Pattern filter.
Narrative: Quality-steered. Concepts: Tone tags. Prompt Eng: Versioned in Langfuse.
UI: Styled output. Player Exp: Playtester invite. Infra: Concurrency stress. Sharing: None. Scenes: Scene tracking.

**Gates for v3**: Quality scores above threshold for 80%+ of scenario seeds. Content
richness metrics improve vs v2.0 baseline. Playtester harness runs 50+ sessions without
pipeline failures. Human playtester feedback validates automated quality scores.

### v3: Production & Players 📋
Simulation: Production-scale. Gameplay: Quest arcs. Game Systems: OSS baseline.
Difficulty: Player-configured. Progression: Achievements.
Economy: Static resources. NPC Society: Emergent stories. Save/Load: Save sharing. Maps/Travel: Interactive map. Image Gen: Scene illustrations.
Multiplayer: Invite-only private. Genesis: Adaptive Genesis. Worlds: Community seeds.
Quality: Human-validated. Therapeutic: None. Context Eng: Dynamic context. Safety: Sentiment monitoring.
Narrative: Beat-tracked. Concepts: Concept maps. Prompt Eng: Meta-prompts.
UI: Character sheet + map. Player Exp: Accounts + hosted. Infra: Production deploy. Sharing: Story export. Scenes: Scene export.

**Gates for v4**: Production instance handles concurrent players without degradation.
Zero-downtime deployment. CI catches regressions before merge. Observability provides
actionable alerts.

### v4: Multiverse & Self-Hosting 🔮
Simulation: Multiverse depth. Gameplay: Decision-matrix turns. Game Systems: Multi-system.
Difficulty: System-defined. Progression: Community badges.
Economy: Dynamic trade. NPC Society: Cross-universe NPCs. Save/Load: Cross-universe saves. Maps/Travel: Cross-universe maps. Image Gen: Style consistency.
Multiplayer: P2P public sharing. Genesis: Guided Genesis. Worlds: Player-shared.
Quality: Continuous monitoring. Therapeutic: Personality depth. Context Eng: Cross-agent context. Safety: Crisis detection.
Narrative: Decision matrix. Concepts: Thematic resonance. Prompt Eng: Prompt chains.
UI: Voice + access. Player Exp: Public launch. Infra: Self-host. Sharing: Character passport. Scenes: Scene import.

### v5: The Long Vision 🌅
Simulation: Full depth. Gameplay: Multi-perspective turns. Game Systems: Player-defined.
Difficulty: Adaptive difficulty. Progression: Player-defined.
Economy: Full simulation. NPC Society: Player impact. Save/Load: Save editing. Maps/Travel: Dynamic discovery. Image Gen: Player-customizable.
Multiplayer: Central Nexus. Genesis: Collaborative Genesis. Worlds: Player-authored.
Quality: Full pipeline. Therapeutic: Healing framework. Context Eng: Self-optimizing. Safety: Full consent.
Narrative: Multi-perspective. Concepts: Steering creation. Prompt Eng: Self-improving.
UI: Full client. Player Exp: Mature platform. Infra: P2P tracker. Sharing: Community. Scenes: Scene library.

---

## Design Principles

1. **Threads, not buckets.** Big ideas mature across versions. Each version
   advances every thread by at least one phase.

2. **Build the bones before the flesh.** Simulation → quality → production →
   multiverse → therapeutic. Each layer must be solid before the next matters.

3. **Personality before therapy.** v1-v4 build personality depth as game
   mechanics (traits, growth, emotional weight). v5 adds therapeutic intent
   on top of an already-rich system.

4. **Solo before social.** The game must be compelling alone before anyone
   will invite friends. v1-v2.1 are solo. Multiplayer begins at v3.

5. **Self-host before P2P.** Players run their own instances (v3 invite, v4
   self-host distribution) before a central tracker connects them (v5).

6. **The vision matures as we prove.** Each version unlocks new possibilities.
   We design vNext after vCurrent ships.

7. **Safety grows with stakes.** Stub interfaces at v1. Real implementations
   arrive when the features they protect arrive.

8. **Each version is a complete, playable game.** Not a framework. A game
   that happens to lay foundation for the next.

9. **Explore before committing.** Features with unknown feasibility (TLC Monks,
   cross-universe travel, therapeutic integration) get research spikes and
   prototypes before graduating to scheduled phases.

---

## Immediate Actions

1. **Merge v2.0** — unblocks everything
2. **Audit v2.1 code** — what exists vs expanded scope
3. **Spike: Decision Matrix** — test narrative quality impact
4. **Draft v2.1 content richness specs** — procedural locations, dynamic quests,
   faction webs, tone calibration
5. **Evaluate ttadev dependency** — test integration in throwaway branch
6. **Keep this document updated** — the vision matures as we build
