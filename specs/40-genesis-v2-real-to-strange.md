# S40 — Genesis v2: Real→Strange

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.0
> **Implementation Fit**: ❌ Not Started
> **Level**: 2 — Simulation
> **Supersedes**: v1 S02 (Genesis Onboarding)
> **Dependencies**: S29 (Universe as First-Class Entity), S39 (Universe Composition Model)
> **Related**: S34 (Diegetic Time), S37 (World Memory Model), S41 (Scenario Seed Library, v2.1+)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

v1 Genesis (S02) follows a 5-act structure: Building World → Slip Phase →
Building Character → First Light → The Becoming. It works, but the narrator
is a voice without a presence — it exists outside the world, observing.
One of v1's deferred acceptance criteria (AC-2.3) requires that the first
post-Genesis turn references Genesis-established elements by name; this was
never enforced because the narrator had no in-world identity to anchor to.

S40 replaces v1 S02's Genesis with a **7-phase Real→Strange arc** that promotes
the old TTA design doc's narrator philosophy: *the narrator is a shapeless void
entity that progressively takes in-world form, becoming the player's guide.*

The expanded arc adds a **Void** phase before world-building (grounding the
narrator's first awareness) and replaces the single "Becoming" act with a
two-beat close: **Becoming** (narrator finds form) + **Threshold** (player
crosses into the story). The Threshold phase enforces AC-2.3 by construction.

S40 also integrates S39's composition vocabulary: the player's responses in
Phase 2 (Building World) are mapped to themes and tropes that seed the
Universe's `config["composition"]` block.

---

## 2. Structural Relationship to v1 S02

| v1 S02 Act | v2 S40 Phase | Changes |
|------------|-------------|---------|
| *(none)* | Phase 1: Void | New. Establishes narrator as void entity. Seeds the universe. |
| Act I: Building World | Phase 2: Building World | Expanded. Now seeds `UniverseComposition` (S39). |
| Act II: Slip Phase | Phase 3: Slip | Unchanged structurally. Still the real→strange transition. |
| Act III: The Stranger | Phase 4: Building Character | Unchanged. Character emerges from reactions. |
| Act IV: The Ripple | Phase 5: First Light | Renamed. Added: narrator takes partial form. |
| Act V: The Threshold | Phase 6: Becoming | Narrator takes full in-world form. Player names character. |
| *(none)* | Phase 7: Threshold | New. Explicit handoff. First post-Genesis turn seeded. |

**v1 S02 remains closed**. Its 5-act normative content is preserved as historical
record. At v2.0 release, the Genesis orchestrator loads S40's 7-phase config.
S02 becomes a closed spec with no active code path.

---

## 3. Design Philosophy

### 3.1 The Narrator is a Character

The narrator is not a neutral omniscient voice — it is a *void entity* with its
own arc. At Phase 1 it has no form, no name, no world. By Phase 6 it has a
recognizable presence in the world (a figure in the periphery, a voice with
texture, an environment that speaks). This arc makes the handoff to gameplay
feel like meeting a guide rather than finishing a tutorial.

### 3.2 Real→Strange as Narrative Arc

The "real-to-strange" arc is TTA's founding design insight: the player enters
through a mundane moment (a bus stop, a library, a café) and is drawn into
something stranger. Phase 3 (Slip) is the fulcrum. The narrator's increasing
in-world form tracks the player's movement deeper into the strange.

### 3.3 Character Emerges, Is Not Chosen

Character creation remains behavioral (v1 FR-3.2): the player's reactions to
the world reveal traits, which the narrator reflects back. Phase 4 infers
traits; Phase 5 reflects them; Phase 6 names them. No stat sliders.

### 3.4 AC-2.3 Resolved by Construction

v1's deferred AC-2.3 ("first post-Genesis turn references Genesis elements by
name") is resolved in Phase 7 (Threshold). The Genesis orchestrator MUST
inject at least two named elements from earlier phases (character name, a
location, a named NPC, a trait) into the first-turn generation context as
hard-injected tokens. The LLM cannot omit them — they are injected as
structured fields, not just narrative hints.

---

## 4. User Stories

> **US-40.1** — **As a** new player, my experience starts in a moment that feels
> familiar — a bus stop, a library — before the strange bleeds in, so I'm
> eased into TTA's world rather than dropped into a generic fantasy.

> **US-40.2** — **As a** player, the narrator feels like a specific presence, not
> a generic voice. By the time we reach gameplay, I feel I've met my guide.

> **US-40.3** — **As a** player, when my first gameplay turn arrives, the narrative
> immediately references the world I built and the character I became, so there
> is no jarring gap between Genesis and gameplay.

> **US-40.4** — **As a** player, my character's traits are revealed to me, not chosen
> — the system shows me who I am from how I behaved during Genesis.

> **US-40.5** — **As a** universe author, the composition I defined in S39 is woven
> into the world that Genesis generates — the themes and tropes I chose appear
> naturally in the narrator's world-building prompts.

---

## 5. Functional Requirements — The 7 Phases

### FR-40.01 — Phase Invariants

These rules apply to ALL seven phases:

- **FR-40.01a**: Each phase MUST include a minimum of 2 player interactions
  (inherited from v1 S02 FR-1.7). No phase may be a non-interactive cutscene.
- **FR-40.01b**: Phase state MUST be persisted to Postgres between player
  interactions. Mid-Genesis reconnect MUST resume from the last completed
  interaction within the current phase.
- **FR-40.01c**: All phases MUST complete in total under 10 minutes for a
  moderately-paced player (10-30s response times). Each phase targets ≤ 2 minutes.
- **FR-40.01d**: Harmful content during any phase MUST redirect (not corrupt
  Genesis state) per v1 S02 AC-2.7. The phase is replayed from the last safe
  interaction.

### FR-40.02 — Phase 1: Void

*The narrator has no form, no world — only awareness.*

**Goal**: Establish the narrator's void presence; seed the universe entity.

1. A `Universe` entity (S29) is created with a generated seed (S39).
2. The narrator addresses the player from the void: pure potential, no world yet.
   Tone: abstract, cosmic, gently curious.
3. The player's first response is any free-form expression. The system captures
   it as the player's "grounding phrase" — stored in genesis state.
4. On interaction 2, the narrator acknowledges the grounding phrase and asks the
   player to hold it as the world forms around it.
5. **Output**: genesis_state["seed_phrase"] populated; Universe entity created.

### FR-40.03 — Phase 2: Building World

*The world crystallizes from the player's responses.*

**Goal**: Establish the universe's setting, atmosphere, and initial S39 composition.

1. The narrator presents 2-3 world-seeding prompts derived from the universe's
   `primary_genre` (default: inferred from the player's seed phrase via LLM).
2. Player responses map to `ThemeSpec` and `TropeSpec` candidates in S39's
   open vocabulary. The mapping is LLM-assisted, not rule-based.
3. At least one location (a named place where the player's story begins) MUST
   be established before Phase 2 ends.
4. At least one recurring NPC is introduced or hinted at.
5. **Output**: `UniverseComposition` (S39) committed to `universes.config`;
   world graph seeded in Neo4j with at least 2 locations and 1 NPC.
   `WorldTime` (S34) initialized to tick 0.

### FR-40.04 — Phase 3: Slip

*The player crosses from the familiar into the strange.*

**Goal**: The pivot point of the real→strange arc. A concrete in-world event
breaks the mundane and pulls the player into something stranger.

1. The slip event MUST be grounded in the world established in Phase 2.
   It is NOT generic — it MUST reference at least one named element from Phase 2.
2. Two interaction types are supported:
   - **Mundane slip**: the player notices something impossible in a familiar setting
     (light bends wrong; a figure appears twice; a conversation loops).
   - **Threshold slip**: the player steps through a physical or narrative threshold
     into an overtly strange space.
3. Universe author may set `genesis.slip_type` in `config` to prefer one type.
   Default: inferred from genre (fantasy → threshold; horror → mundane).
4. **Output**: genesis_state["slip_event"] recorded. At least one S36-eligible
   `ConsequenceRecord` candidate noted for the first gameplay turn.

### FR-40.05 — Phase 4: Building Character

*Who is the player? Their reactions reveal them.*

**Goal**: Infer 2-3 character traits from the player's behavioral responses.

1. 2-3 ambiguous situations are presented. Each situation has no clearly right
   answer. Player responses reveal temperament, not skill.
2. After each response the narrator reflects back: not judging, but noting.
3. At the end of Phase 4, the system infers traits using the v1 character
   inference heuristic (S06 FR-3.1). Traits are stored in genesis_state
   but NOT shown to the player yet (that is Phase 5's job).
4. **Output**: genesis_state["inferred_traits"] = [2-3 trait strings].

### FR-40.06 — Phase 5: First Light

*The player sees themselves for the first time. The narrator takes partial form.*

**Goal**: Reflect the character back; narrator begins to have texture.

1. The narrator delivers a "mirror moment" — a scene where the player's inferred
   traits are described in narrative form, not as a stat sheet.
   Example: "You are someone who hesitates at thresholds. Who holds the door.
   Who watches before acting."
2. The player MAY accept or refine one trait. Acceptance proceeds; refinement
   offers a single alternative (v1 AC-2.9 pattern).
3. The narrator gains a hint of physical form — a texture, a shadow, a sound.
   The specific form is derived from the universe's `primary_genre` and `prose.voice`.
4. **Output**: genesis_state["confirmed_traits"] = [final 2-3 traits];
   genesis_state["narrator_form_hint"] stored.

### FR-40.07 — Phase 6: Becoming

*The narrator takes full in-world form. The player gives the character a name.*

**Goal**: Complete the narrator's character arc; anchor the player's identity.

1. The narrator becomes a fully formed presence — described in 2-3 sentences.
   This entity will accompany the player through gameplay (it is not a player-
   controlled NPC; it is the voice of the world's witness).
2. "What do they call you?" — the player names the character. The system stores
   the name. If the player provides no name, a name is offered based on traits.
3. The narrator says the player's name once, anchoring the identity.
4. **Output**: genesis_state["character_name"] = player_name; character NPC
   created in the world graph with confirmed traits and genesis start location.

### FR-40.08 — Phase 7: Threshold

*The player steps into the story. Genesis ends; gameplay begins.*

**Goal**: Explicit handoff. Enforce AC-2.3. Seed the first gameplay turn.

1. A brief closing scene (1-2 interactions) brings the player to the story's
   opening moment. The scene MUST be set at the Phase 2 starting location.
2. The genesis orchestrator constructs a **first-turn seed** that MUST include:
   - Character name (Phase 6)
   - Starting location name (Phase 2)
   - At least one inferred trait (Phase 5)
   - At least one slip-event reference (Phase 3)
3. The first-turn seed is stored as structured fields in the game session's
   `MemoryRecord` (S37) at turn 0 with `importance_score = 1.0` (maximum).
4. The generation model for the FIRST gameplay turn MUST receive the first-turn
   seed as hard-injected context. This enforces AC-2.3 structurally.
5. **FR-40.08a** (closes v1 AC-2.3): The first post-Genesis narrative MUST
   reference at least two named elements from the first-turn seed by name.
   This is validated by asserting that the generated text contains the
   character name AND at least one of (location name, trait phrase).

---

## 6. Non-Functional Requirements

### NFR-40.01 — Time Budget
Total Genesis (Phases 1–7) MUST complete in under 10 minutes for a moderately-
paced player (v1 AC-2.4 equivalent). Each phase targets ≤ 2 minutes.

### NFR-40.02 — Resumability
Mid-Genesis disconnect MUST resume from the last completed interaction within
the current phase. Genesis state MUST be persisted to Postgres after every
player interaction.

### NFR-40.03 — Variance
Two Genesis runs on the same universe type MUST produce different narratives
(different location names, different slip events). Variance is ensured by
LLM temperature and the `seed` value (S39 FR-39.11).

### NFR-40.04 — Composition Integration
The universe's `UniverseComposition` (S39) MUST be committed to Postgres before
Phase 3 begins. Downstream S36–S38 systems MUST be able to read composition
config from the universe at any point after Phase 2 completes.

### NFR-40.05 — Observability
Every phase start and end MUST emit a structlog event with `universe_id`,
`session_id`, `phase_name`, and `event` (`start` or `complete`).

---

## 7. User Journeys

### Journey 1: Strange Mundane Opening (Bus Stop Slip)

(Non-normative; illustrates the real→strange arc.)

1. **Phase 1 (Void)**: "You are somewhere between. Not yet arrived. Hold your
   breath." Player: "I'm waiting for the number 12 bus." Grounding phrase stored.
2. **Phase 2 (Building World)**: The narrator describes an ordinary city corner.
   "What year do you think it is? What season?" Player anchors a time and mood.
   Themes inferred: `urban_mundane`, `liminal_space`. Genre-twist: `mundane_cosmic`.
   Universe composition committed.
3. **Phase 3 (Slip)**: "The bus is late. You notice the stop sign has been there
   for 20 minutes. Exactly 20 minutes. The timestamp in your phone confirms it.
   The bus is always 20 minutes late. Has always been."
   Player reacts. Slip event recorded.
4. **Phase 4 (Character)**: Three ambiguous moments unfold. An older woman at the
   stop speaks too directly. A child points at something behind the player.
   Traits inferred: observant, cautious, quietly compassionate.
5. **Phase 5 (First Light)**: "You are someone who notices. Who waits. Who does
   not leave when things become strange." Player accepts.
   Narrator gains: a low voice, slightly too clear, slightly too close.
6. **Phase 6 (Becoming)**: "The voice becomes a figure at the edge of your vision.
   It has learned your face. What do they call you?" Player: "Alex."
7. **Phase 7 (Threshold)**: "The bus arrives. The number 12. You have never seen
   it before, Alex, though you have waited here your whole life." First-turn seed
   injected. Gameplay begins with character name "Alex", location "Bus Stop 12".

---

## 8. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | Player disconnects during Phase 3 | Resume from last safe interaction in Phase 3 on reconnect |
| E2 | Harmful content in Phase 1 seed phrase | Redirect; don't store harmful phrase; replay Phase 1 interaction |
| E3 | Player refuses to name character in Phase 6 | Offer a name derived from traits; player may accept or modify |
| E4 | Player completes Genesis in < 2 minutes (very terse) | Terse handling (v1 AC-2.8 pattern): narrator expands with follow-up questions before phase completes |
| E5 | `config["genesis"]["slip_type"]` is an unknown value | Use genre-inferred default; log WARNING |
| E6 | LLM fails to generate slip event (Phase 3) | Retry once; if retry fails, use template slip event from Scenario Seed Library fallback |
| E7 | Second Genesis on same universe (player restarts) | A new session is created; the universe entity persists; a second genesis seeds a new character and session. World graph gains a second character. |
| E8 | First gameplay turn fails AC-2.3 assertion | Log WARNING; do NOT block turn; increment tta_genesis_ac2_3_miss_total counter for monitoring |

---

## 9. Acceptance Criteria (Gherkin)

```gherkin
Feature: Genesis v2 — Real→Strange

  Background:
    Given a universe with composition config (primary_genre = "urban_fantasy")
    And genesis.slip_type = "mundane"

  Scenario: AC-40.01 — All 7 phases complete in order
    When a new player completes Genesis
    Then phases 1 through 7 are executed in sequence
    And each phase produces at least 2 player interactions
    And genesis_state contains: seed_phrase, slip_event, inferred_traits, character_name

  Scenario: AC-40.02 — UniverseComposition committed before Phase 3
    Given Phase 2 completes with player responses suggesting gothic themes
    When Phase 3 begins
    Then config["composition"] is committed to Postgres
    And composition contains at least one theme derived from player responses

  Scenario: AC-40.03 — Character traits inferred from behavior (no stat selection)
    Given Phase 4 presents 3 ambiguous situations
    When the player responds to each
    Then inferred_traits contains 2-3 traits
    And no trait was directly selected by the player

  Scenario: AC-40.04 — Player can refine one trait in Phase 5
    Given Phase 5 presents confirmed traits
    When the player rejects one trait
    Then an alternative trait is offered
    And the player may accept the alternative

  Scenario: AC-40.05 — AC-2.3 closed: first turn references genesis elements
    Given Genesis completes and Phase 7 seeds the first turn
    When the first post-Genesis narrative is generated
    Then the narrative contains the character name
    And the narrative contains at least one of: starting location name, trait phrase

  Scenario: AC-40.06 — Mid-Genesis reconnect resumes correctly
    Given a player disconnects during Phase 3
    When they reconnect
    Then Genesis resumes from the last completed interaction in Phase 3
    And no earlier phase is replayed

  Scenario: AC-40.07 — Terse player receives follow-up expansion
    Given a player responds with a single word to every Phase 4 prompt
    When Phase 4 is processed
    Then the narrator generates a follow-up question before the phase ends
    And inferred_traits is populated with at least 2 traits

  Scenario: AC-40.08 — Harmful content does not corrupt Genesis state
    Given a player submits harmful content during Phase 2
    When the input is processed
    Then the harmful content is not stored in genesis_state
    And the Phase 2 interaction is replayed from the last safe point
```

---

## 10. Out of Scope

- Canonical slip event templates (bus stop, café, library) — S41 Scenario Seed Library.
- The specific LLM prompts for each phase — S09 Prompt Registry.
- Narrator form descriptions per genre — S41 seed library templates.
- Multi-player Genesis (two actors starting together) — S57 (v4+).
- Genesis replay or branching (alternate choices, undo) — future spec.

---

## 11. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-40.01 | Minimum-viable WorldSeed field set — hard-gate or soft-prompt to continue? | ✅ Resolved | **Soft-prompt with auto-defaults.** Only `seed` (auto-generated) and `primary_genre` (defaults to `"fantasy"`) are hard requirements. All composition fields are optional with sensible defaults. If the player's responses don't yield clear theme/trope mappings, default composition applies. No hard gate that blocks Genesis completion. |
| OQ-40.02 | Should Phase 7 first-turn seed be stored as a MemoryRecord (S37) or a separate genesis_seed field? | ✅ Resolved | **MemoryRecord at turn 0 with importance_score = 1.0** (FR-40.08). This integrates naturally with S37's working memory tier and ensures the first-turn seed is always injected (working tier is never compressed). |
| OQ-40.03 | Does S40 Genesis replace v1's genesis orchestrator entirely, or can they coexist? | ✅ Resolved | **Full replacement at v2.0 release.** v1 S02 code paths are disabled. S40 orchestrator handles all new sessions. Existing v1 sessions keep their genesis state as historical record; no migration needed (they're already in gameplay). |

---

## Appendix A — Phase Summary Table

| Phase | Name | Narrative Beat | Key Output |
|-------|------|----------------|------------|
| 1 | Void | Narrator aware, world absent | `seed_phrase`, Universe entity created |
| 2 | Building World | World crystallizes from player | `UniverseComposition` committed, world graph seeded |
| 3 | Slip | The real→strange pivot | `slip_event`, first consequence seed |
| 4 | Building Character | Traits inferred from behavior | `inferred_traits` |
| 5 | First Light | Mirror moment; narrator gains form | `confirmed_traits`, `narrator_form_hint` |
| 6 | Becoming | Narrator fully formed; player named | `character_name`, character NPC created |
| 7 | Threshold | Genesis→gameplay handoff | `first_turn_seed` (MemoryRecord turn 0, importance 1.0) |

## Appendix B — v1 AC Disposition

| v1 AC | Status in S40 |
|--------|--------------|
| AC-2.1 Genesis begins with narrative prompt | ✅ Inherited — Phase 1 is a narrative prompt. |
| AC-2.2 World graph created once on Genesis completion | ✅ Tightened — world graph seeded at end of Phase 2. Idempotent. |
| AC-2.3 First turn references genesis elements by name | ✅ **Closed** — FR-40.08, AC-40.05. Hard injection via MemoryRecord turn-0 seed. |
| AC-2.4 Complete within 5–10 minutes | ✅ Inherited — NFR-40.01. |
| AC-2.5 Disconnect resume from same act | ✅ Tightened — FR-40.01b, AC-40.06. Per-interaction persistence. |
| AC-2.6 Second playthrough variance | ✅ Inherited — NFR-40.03. |
| AC-2.7 Harmful content redirect | ✅ Inherited — FR-40.01d, AC-40.08. |
| AC-2.8 Terse player follow-up | ✅ Inherited — AC-40.07. |
| AC-2.9 Rejected identity alternative | ✅ Inherited — AC-40.04. Applies to trait in Phase 5 and name in Phase 6. |
| AC-2.10 No visible Genesis/gameplay boundary | ✅ Inherited — Phase 7 Threshold is designed as a seamless handoff. |

## Appendix C — Pipeline Position

```
Player opens new session (no existing game):
  1. Universe entity created (S29) with seed (S39)          [Phase 1]
  2. Genesis orchestrator starts Phase 1
     ─── Phase 1: Void (2+ interactions)
     ─── Phase 2: Building World (2-3 interactions)
          └─► UniverseComposition committed to Postgres
          └─► World graph seeded in Neo4j
          └─► WorldTime initialized (S34)
     ─── Phase 3: Slip (2+ interactions)
     ─── Phase 4: Building Character (2-3 interactions)
     ─── Phase 5: First Light (2+ interactions)
     ─── Phase 6: Becoming (2+ interactions)
          └─► Character NPC created in world graph
     ─── Phase 7: Threshold (1-2 interactions)
          └─► MemoryRecord turn-0 seed written (S37, importance=1.0)
  3. Genesis complete → GameState.game_phase = "gameplay"
  4. First gameplay turn: standard turn pipeline (S08) with
     Phase-7 seed as highest-importance working memory
```
