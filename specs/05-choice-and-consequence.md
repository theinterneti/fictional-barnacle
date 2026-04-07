# S05 — Choice & Consequence

> **Status**: 📝 Draft
> **Level**: 1 — Core Game Experience
> **Dependencies**: S00
> **Last Updated**: 2025-07-24

---

## Purpose

Choice and consequence is what separates TTA from a chatbot that tells you a story.
In a chatbot, your inputs are prompts. In TTA, your inputs are *decisions* — and
decisions have weight. They change the world. They change relationships. They come
back to haunt you, or to save you, twenty turns later.

This spec defines how player agency works: how choices are presented, how consequences
are tracked, how the story branches and converges, and how the system ensures that
what you do *matters* without collapsing under the combinatorial weight of infinite
possibility.

The design philosophy is simple: **consequences should feel inevitable in hindsight.**
Not random. Not punitive. Not telegraphed. Inevitable.

---

## User Stories

### Agency & Impact

- **US-5.1**: As a player, I want my choices to visibly affect the world, so that I
  feel like a participant, not an observer.

- **US-5.2**: As a player, I want to be surprised when an earlier choice has
  consequences I didn't foresee — a satisfying "oh no" or "oh YES" moment.

- **US-5.3**: As a player, I want different choices to lead to genuinely different
  outcomes, not just different dialogue that leads to the same result.

### Choice Presentation

- **US-5.4**: As a player, I want to make choices through natural language input, not
  just numbered menus, so that the experience feels conversational.

- **US-5.5**: As a player, I sometimes want the game to suggest possible actions when
  I'm stuck, without making me feel like I *have to* pick from a list.

- **US-5.6**: As a player, I want to be able to attempt anything reasonable — not just
  the options the game thought of — and have the world respond coherently.

### Consequence Clarity

- **US-5.7**: As a player, I want to understand *why* something happened to me — even
  if the connection to my earlier choice isn't obvious, once revealed it should make
  sense.

- **US-5.8**: As a player, I want to feel the weight of serious choices *before* I
  make them — the game should signal when something important is at stake.

- **US-5.9**: As a player, I want some choices to have ambiguous consequences — where
  it's not clear if what I did was "right" — because that's what makes a story
  interesting.

### Branching & Replayability

- **US-5.10**: As a player, I want to wonder "what if I had done that differently?"
  — the sense that other paths existed and were real.

- **US-5.11**: As a player who replays, I want to discover that making different
  choices produces meaningfully different stories, not cosmetic variations.

---

## Functional Requirements

### FR-1: Choice Presentation

**FR-1.1** — Player choices are made through **free-text input** as the primary
mechanism. The player types what they want to do, say, or think.

**FR-1.2** — The system MAY surface **suggested actions** as an optional assist.
These are 2-4 brief options displayed below the input field:

```
> What do you do?

  Suggestions:
  • Confront the merchant about the forged letter
  • Slip away before anyone notices
  • Ask Sera what she thinks
```

**FR-1.3** — Suggested actions are:
- **Optional**: The player can always type their own input instead.
- **Non-exhaustive**: They don't represent all possible actions.
- **Contextual**: Generated from current scene state, active NPCs, and story threads.
- **Varied**: They represent different *types* of approaches (aggressive, cautious,
  social, investigative) — not just variants of one approach.

**FR-1.4** — Suggested actions MUST NOT:
- Reveal hidden information ("Ask about the trap" when the player doesn't know
  there's a trap).
- Telegraph the "right" answer through framing.
- Include system commands.
- Repeat across consecutive turns.

**FR-1.5** — The player can toggle suggested actions on/off in settings. Default: on.

**FR-1.6** — If the player types something the game cannot interpret (truly
nonsensical input), the system responds in-world with a request for clarity:
*"You start to act, but something holds you back. What exactly do you intend?"*

### FR-2: Choice Types

**FR-2.1** — The system recognizes these choice categories (internally, not shown
to the player):

| Category | Description | Consequence Profile |
|----------|-------------|-------------------|
| **Action** | Physical acts | Immediate physical consequences |
| **Dialogue** | What the player says | Relationship and information consequences |
| **Movement** | Where the player goes | Exposure to new content and events |
| **Strategic** | Planning and resource decisions | Delayed, cascading consequences |
| **Moral** | Ethical decisions | Reputation, relationship, and narrative-arc consequences |
| **Refusal** | Choosing NOT to act | Consequences of inaction |

**FR-2.2** — Every player input is classified into one or more categories. The
classification influences:
- Which consequence models are evaluated
- How consequences are timed (immediate vs. delayed)
- What world state is updated

**FR-2.3** — **Refusal choices** are first-class choices. If an NPC asks the player
to do something and the player ignores it or refuses, that IS a decision with
consequences. The system tracks refusals.

### FR-3: Consequence Model

**FR-3.1** — Consequences operate on three timescales:

| Timescale | Trigger Window | Example |
|-----------|---------------|---------|
| **Immediate** | Same turn | Punch someone → they fall down |
| **Short-term** | 1-10 turns | Insult the guard → increased patrol scrutiny |
| **Long-term** | 10+ turns / chapters | Save the village → they remember you in Act 3 |

**FR-3.2** — Consequences are tracked as **consequence chains**: linked sequences of
cause and effect.

```
Consequence Chain Example:
  [Turn 5] Player steals from merchant
    → [Immediate] Player gains item. Merchant doesn't notice (yet).
    → [Turn 12] Merchant discovers theft. Reports to authorities.
    → [Turn 18] Wanted poster appears. Guards are suspicious.
    → [Turn 30] Player is recognized in a different town. Confrontation.
    → [Turn 45] The merchant's son seeks revenge.
```

**FR-3.3** — Each consequence chain entry contains:
- **Trigger**: What event caused this consequence
- **Effect**: What changes in the world (state mutations, see S04)
- **Visibility**: Is the player aware this is happening?
- **Resolution**: How/when does this chain end?
- **Narrative hook**: How should the engine surface this consequence in prose?

**FR-3.4** — Consequence chains can **branch**. A single action can spawn multiple
independent consequence chains:

```
  [Turn 5] Player sets fire to warehouse
    Chain A: Physical damage to warehouse → insurance investigation → ...
    Chain B: Merchant loses goods → economic impact on town → ...
    Chain C: NPC child was playing nearby → NPC parent is furious → ...
```

**FR-3.5** — Consequence chains can **merge**. Two independent chains can converge
when their effects interact:

```
  Chain A: Player earns guard's trust (from helping patrol)
  Chain B: Player is wanted for theft
  → Merge: The guard discovers the warrant. Trust is tested. Does loyalty
    outweigh duty?
```

**FR-3.6** — The system MUST cap active consequence chains at a manageable number
(suggested: 20-30 per story). Chains that have fully resolved are archived.
Chains that are dormant for 50+ turns without activation MAY be retired with
a quiet narrative resolution.

### FR-4: Branching & Convergence

**FR-4.1** — TTA's story structure is a **directed graph**, not a tree. Stories
branch AND converge. Multiple paths can lead to the same narrative node, and
single paths can fork.

**FR-4.2** — The system does NOT pre-generate branches. Branching is **emergent**:
the narrative engine generates each turn based on current state, which is shaped
by all previous choices. There is no hidden "path A" vs "path B" — there is only
"the state of the world right now."

**FR-4.3** — This means branching is theoretically infinite. The constraint is not
the branch structure but the **consequence model** — only tracked consequences
produce observable differences. Untracked choices produce atmospheric variation
but converge toward the same narrative threads.

**FR-4.4** — The system maintains **narrative anchors**: key story events that the
narrative tends toward regardless of path. These are established during Genesis
(the story hook) and evolved during play. The story has a *direction*, even if
the route is open.

**FR-4.5** — Narrative anchors are NOT railroads. The player can derail an anchor
through sufficient effort. When an anchor is invalidated, the system generates
a replacement anchor. The story always has a destination, but the destination
can change.

**FR-4.6** — The system MUST track a **divergence score** that measures how far the
current story has deviated from the nearest narrative anchor. High divergence
triggers gentle narrative steering (NPCs mention the abandoned thread, events
echo the theme). Very high divergence triggers anchor replacement.

### FR-5: Reversibility

**FR-5.1** — Choices exist on a **reversibility spectrum**:

| Category | Reversible? | Example |
|----------|-------------|---------|
| **Trivial** | Fully | Going left instead of right |
| **Moderate** | Partially | Insulting someone (can apologize, but they remember) |
| **Significant** | With effort | Breaking an alliance (can rebuild, but trust is damaged) |
| **Permanent** | Never | A character death caused by player action |

**FR-5.2** — The system MUST communicate reversibility through narrative signals.
Before a permanent choice, the narrative should slow down, create weight:
*"Your hand tightens on the blade. This moment feels different. Final.
There won't be a way back from this."*

**FR-5.3** — Players CANNOT undo choices through game mechanics (no "undo" button,
no reloading saves — see S01 FR-5.6). But they CAN address consequences through
subsequent choices: apologies, reparations, finding alternatives.

**FR-5.4** — The system MUST track choice reversibility metadata for each consequence
chain. This data is used by the narrative engine to appropriately weight the
significance of moments.

### FR-6: Meaningful vs. Cosmetic Choices

**FR-6.1** — Every choice falls on a spectrum of impact:

| Level | Impact | Example |
|-------|--------|---------|
| **Cosmetic** | Changes flavor text only | Choosing to walk vs. jog to the market |
| **Atmospheric** | Changes tone/mood | Being polite vs. brusque to a shopkeeper |
| **Consequential** | Changes world state | Helping the rebels vs. reporting them |
| **Pivotal** | Changes story direction | Betraying your mentor |
| **Defining** | Changes the nature of the story | Choosing mercy when the genre expects vengeance |

**FR-6.2** — The system MUST ensure a minimum ratio of consequential+ choices.
Target: at least 30% of player inputs in a session should have consequences
beyond the immediate turn.

**FR-6.3** — Cosmetic and atmospheric choices are still valuable — they give the
player agency in *how* they experience the story, even when the *what* doesn't
change much. The engine should make even cosmetic choices feel acknowledged.

**FR-6.4** — The system MUST NOT reveal the impact level of a choice to the player
before they make it. Part of the design is not knowing which choices matter most
until the consequences arrive.

### FR-7: Hidden Consequences

**FR-7.1** — Some consequences are deliberately hidden from the player until they
manifest. The player doesn't know:
- That the merchant noticed the theft (until the wanted poster appears)
- That the NPC they helped is secretly an assassin (until the reveal)
- That choosing to rest cost them time while a rival advanced (until they arrive
  too late)

**FR-7.2** — Hidden consequences MUST feel fair when revealed. The player should be
able to think back and say "I should have seen that coming" — not "that was random
and unfair."

**FR-7.3** — The system tracks hidden consequences as invisible entries in the
consequence chain. They become visible when:
- The consequence manifests narratively
- An NPC reveals information
- The player discovers evidence
- Time passes and the consequence naturally surfaces

**FR-7.4** — The system SHOULD provide subtle foreshadowing for major hidden
consequences. Not a spoiler — a whisper. An NPC acting nervous, a detail that
seems off, a throwaway line that gains meaning later.

### FR-8: Managing Complexity (The Butterfly Effect Problem)

**FR-8.1** — Not every choice can have infinite cascading consequences. The system
manages complexity through:

- **Consequence budgets**: Each choice is assigned a consequence weight. Trivial
  choices have near-zero weight. The total active consequence weight is capped.
- **Natural resolution**: Consequence chains resolve and close. A theft chain
  resolves when the player is caught, acquitted, or the statute of limitations
  passes (in-world).
- **Consolidation**: Multiple related chains are merged into a single chain when
  they converge on the same outcome.
- **Pruning**: Chains that have been dormant too long are quietly resolved
  off-screen with minimal narrative acknowledgment.

**FR-8.2** — The system prioritizes consequence chains based on:
1. Player visibility (will the player notice if this chain resolves quietly?)
2. Story relevance (does this chain connect to the main narrative arc?)
3. Emotional weight (does this chain involve a character the player cares about?)
4. Recency (newer chains are more salient than old ones)

**FR-8.3** — The system MUST NEVER drop a consequence that the player explicitly
created and would remember. If the player burned down the orphanage, that
consequence chain stays active until resolved narratively, regardless of budget.

**FR-8.4** — When pruning a chain, the system creates a brief narrative closure:
*"You hear that the merchant you argued with last month has moved to another town.
Some feuds just fade."* This is closure, not a hand-wave.

---

## Non-Functional Requirements

- **NFR-5.1** — Consequence evaluation (all active chains checked against current
  turn) MUST complete within 300ms.
- **NFR-5.2** — The system MUST support at least 30 active consequence chains
  simultaneously without performance degradation.
- **NFR-5.3** — Suggested action generation MUST complete within 500ms.
- **NFR-5.4** — Consequence chain persistence MUST survive server restarts and
  session boundaries.
- **NFR-5.5** — The divergence score calculation MUST complete within 100ms.
- **NFR-5.6** — Consequence chain history (including resolved chains) MUST be
  retained for the life of the story for narrative callback purposes.

---

## User Journeys

### Journey 1: The Stolen Letter

1. Turn 10: Player finds a letter on the ground. Types: "I read it." The letter
   reveals a conspiracy. Consequence chain spawned: player has forbidden knowledge.
2. Turn 15: Player is approached by an NPC who asks if they've "seen anything
   unusual." Player lies: "No." Consequence: NPC is suspicious (hidden), player
   relationship with NPC takes a trust penalty.
3. Turn 30: The conspiracy advances. Player overhears a conversation that confirms
   what the letter said. They have a choice: intervene or stay hidden.
4. Turn 31: Player intervenes. This triggers a consequence cascade: the conspirators
   know someone is onto them, the NPC from turn 15 realizes the player lied,
   and the political landscape shifts.
5. Turn 45: The NPC from turn 15 confronts the player. "You knew. You knew and you
   lied to my face." The player must deal with the social consequences of their
   turn-15 choice — 30 turns later.

### Journey 2: The Butterfly and the Avalanche

1. Turn 5: Player helps a lost child find their parent. Small kindness. Low-weight
   consequence chain: the family remembers.
2. Turn 50: Player is on trial for a crime (consequence of a different chain).
   The family from turn 5 appears as a character witness. Their testimony sways
   the verdict.
3. The player's small kindness from 45 turns ago saved them. The consequence chain
   from turn 5 resolved in a dramatic and satisfying way.

### Journey 3: Choices That Weight

1. Player discovers that two NPCs they care about have conflicting goals. Helping
   one means hurting the other. There's no "both" option.
2. The narrative slows down. Descriptions become more introspective. Both NPCs
   make their case — neither is wrong.
3. Player makes a choice. The consequence is immediate (one NPC is hurt) and
   long-term (relationship with the other NPC deepens, but guilt lingers).
4. For the next several turns, the narrative carries an undertone of the choice.
   The world is a little different. The player feels the weight.

### Journey 4: The Road Not Taken

1. Player reaches a fork: investigate the ruins or follow the caravan. They choose
   the caravan.
2. Twenty turns later, an NPC mentions that "something terrible happened at the
   old ruins." The player wonders: would that have been different if they'd gone?
3. The answer (unknown to the player) is: maybe. The system tracked a consequence
   chain for the ruins that included a threat. Because the player didn't intervene,
   the threat escalated. The consequence of *not* choosing is real.

---

## Edge Cases

- **EC-5.1**: Player makes the same choice repeatedly (talks to the same NPC about
  the same thing every turn). The NPC's response evolves: patient → impatient →
  refuses to discuss it. The consequence of repetition is social friction.

- **EC-5.2**: Player attempts an action that would break a core story anchor
  (killing the main quest-giver). The world makes it *very difficult* but not
  impossible. If the player succeeds, the story pivots to a new anchor. The game
  doesn't block the choice — it adapts.

- **EC-5.3**: Player's choices create contradictory consequence chains (helps both
  sides of a conflict). The system surfaces the contradiction narratively: both
  sides eventually learn, and the player faces the reckoning.

- **EC-5.4**: Too many consequence chains are active (over the 30-chain cap). System
  consolidates the lowest-priority chains and prunes dormant ones, with narrative
  closure for each.

- **EC-5.5**: Player input is ambiguous about intent ("I deal with the guard").
  System interprets based on context (if weapons are drawn: combat; if in a
  social scene: persuasion) and proceeds. If truly ambiguous, asks for
  clarification in-world.

- **EC-5.6**: Player makes a choice during Genesis (S02) that has consequences in
  gameplay. Genesis choices ARE the first entries in the consequence system. The
  world responds to who the player was from the very beginning.

- **EC-5.7**: Consequences from one story "leak" into another playthrough. This
  MUST NOT happen. Each playthrough has independent consequence tracking. No
  cross-contamination.

- **EC-5.8**: A consequence chain references an NPC who was removed by lazy pruning
  in the world model (S04). The system either restores the NPC or adapts the chain
  to use a substitute. The consequence still fires; the delivery adjusts.

---

## Acceptance Criteria

- **AC-5.1**: Given a player makes a consequential choice, when 10+ turns pass, then
  at least one delayed consequence from that choice manifests narratively.

- **AC-5.2**: Given a player receives suggested actions, when they view the
  suggestions, then at least 3 distinct approaches are offered and none reveal
  hidden information.

- **AC-5.3**: Given a player ignores a request from an NPC, when consequence
  evaluation runs, then the refusal is tracked as a choice with consequences (the
  NPC's disposition changes).

- **AC-5.4**: Given a player is about to make a permanent choice, when the turn
  before the choice is processed, then the narrative contains signals of weight
  and finality.

- **AC-5.5**: Given a hidden consequence chain is active, when 5+ turns pass before
  it triggers, then at least one instance of subtle foreshadowing appeared in
  intervening narration.

- **AC-5.6**: Given 30 active consequence chains, when consequence evaluation runs,
  then all chains are evaluated within 300ms.

- **AC-5.7**: Given a player makes the same choice in two different playthroughs,
  when consequences evaluate, then the chains are independent (no cross-
  contamination).

- **AC-5.8**: Given a dormant consequence chain (50+ turns inactive), when the
  system prunes it, then a brief narrative closure is generated and the chain
  is archived.

- **AC-5.9**: Given a player's choice spawns 3 branching consequence chains, when
  the chains are stored, then each chain is independently trackable and can
  resolve at different times.

- **AC-5.10**: Given the divergence score exceeds the steering threshold, when the
  next turn is processed, then the narrative includes gentle references to the
  abandoned story thread.

---

## Dependencies

| Spec | Relationship |
|------|-------------|
| **S01 — Gameplay Loop** | Consequence chains are evaluated every turn. |
| **S02 — Genesis** | Genesis choices are the first entries in consequence tracking. |
| **S03 — Narrative Engine** | The engine surfaces consequences in prose. |
| **S04 — World Model** | Consequences mutate world state. |
| **S06 — Character System** | Consequences affect NPC relationships and PC traits. |
| **S13 — Storage Schema** | Consequence chains must persist across sessions. |

---

## Open Questions

- **OQ-5.1**: Should the player ever see their consequence chains explicitly (a
  "journal" or "quest log")? Pro: clarity and satisfaction. Con: breaks immersion,
  makes hidden consequences impossible. Leaning: maybe a `/recap` that surfaces
  known consequences but not hidden ones.

- **OQ-5.2**: How do we balance "choices matter" with "the story must reach a
  satisfying conclusion"? If the player makes terrible choices, does the story
  end badly? Or does the engine find a way to make even bad outcomes narratively
  satisfying?

- **OQ-5.3**: Should there be "points of no return" that the player is explicitly
  warned about? Or should the weight be communicated only through narrative tone?

- **OQ-5.4**: How visible should the divergence score / steering mechanism be?
  If players realize the game is steering them, it breaks agency. But if they
  never encounter the main thread again, the story feels aimless.

- **OQ-5.5**: Should moral choices have a "right answer"? TTA's design values rank
  Fun highest — but fun for whom? A morally unambiguous choice is less interesting.
  A truly ambiguous one is more stressful. Where's the balance?

- **OQ-5.6**: How do we prevent the consequence system from making the game feel
  punitive? If every action has consequences, players might become paralyzed.
  The system should reward boldness too.

---

## Out of Scope (v1)

- Consequence visualization (graphs showing cause-and-effect chains)
- Player-facing "what if" speculation
- Cross-playthrough consequence memory
- Moral alignment scores or karma meters
- NPC-NPC consequence chains that don't involve the player
- Faction-level strategy consequences (Risk-style)
- Time-travel or timeline manipulation mechanics
- Choice analytics shared with other players
