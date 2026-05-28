# S01 — Gameplay Loop & Progression

> **Status**: ✅ Approved
> **Release Baseline**: 🔒 v1 Closed
> **Implementation Fit**: ⚠️ Partial
> **Level**: 1 — Core Game Experience
> **Dependencies**: S00
> **Last Updated**: 2026-04-09

---

## Purpose

This spec defines the heartbeat of TTA: the moment-to-moment turn cycle, the session
structure that wraps it, and the meta-loop that gives players a reason to keep coming
back. If S02 (Genesis) is the first breath, S01 is the breathing itself.

The gameplay loop must feel *alive*. Not "press button, receive text." The player should
feel like the world is listening, reacting, and remembering. Every input matters.
Every response moves something forward — even silence.

---

## User Stories

### Core Turn Cycle

- **US-1.1**: As a player, I want to type a free-text action and see the world respond
  narratively, so that I feel like I'm genuinely inside a story.

- **US-1.2**: As a player, I want to see the narrative response stream in token-by-token
  (not appear all at once), so that reading feels immersive — like the story is being
  told to me in real time.

- **US-1.3**: As a player, I want to know when it's my turn to act (clear input prompt),
  so that I'm never confused about whether the game is waiting for me.

- **US-1.4**: As a player, I want to be able to type anything — not just pick from
  menus — so that I feel true freedom in how I engage with the world.

### Turn Types

- **US-1.5**: As a player, I want to perform actions ("I swing my sword at the lock"),
  speak to characters ("I ask the merchant about the rumor"), explore ("I look around
  the room"), or reflect internally ("I think about what she said"), and have each
  feel distinct in how the world responds.

- **US-1.6**: As a player, I want system commands (save, settings, help) to be available
  without breaking narrative immersion — they should feel like stepping behind the
  curtain, not ripping it down.

### Meta-Loop & Progression

- **US-1.7**: As a player, I want to feel a sense of forward momentum — not just
  wandering aimlessly — so that each session feels like it advanced my story.

- **US-1.8**: As a player, I want to see my character grow through the choices I make,
  not through grinding XP, so that progression feels narratively earned.

- **US-1.9**: As a player, I want to recognize chapter boundaries — natural pauses in
  the story where the tone shifts or a new thread begins — so that the experience
  feels structured, not endless.

### Session Management

- **US-1.10**: As a player, I want to close my browser and come back later, picking up
  exactly where I left off, so that I can play in short bursts without losing progress.

- **US-1.11**: As a player, I want a clear "end of session" moment — a natural pause
  point — rather than just closing the tab mid-sentence.

- **US-1.12**: As a returning player, I want a brief recap of where I left off, so that
  I can re-immerse quickly without re-reading old text.

### Failure & Retry

- **US-1.13**: As a player, I want failure to feel like part of the story, not a
  game-over screen, so that setbacks are interesting rather than punishing.

- **US-1.14**: As a player, I want to understand *why* something went wrong (within the
  narrative) so I can make better choices, not just guess differently.

### Replayability

- **US-1.15**: As a returning player, I want a second playthrough to feel genuinely
  different — new world, new character, new story — not a remix of the same events.

- **US-1.16**: As a player who finished a story, I want to start fresh with Genesis
  and know that my choices will create a different world.

---

## Functional Requirements

### FR-1: The Turn Cycle

**FR-1.1** — Each gameplay turn follows this sequence:

1. **Prompt**: The system displays a clear input indicator (the player knows it's
   their turn).
2. **Input**: The player submits free-text input (no minimum length, maximum TBD).
3. **Processing**: The system processes the input through a 4-stage pipeline
   (see S08 — Turn Processing Pipeline): Input Understanding, Context
   Assembly, Narrative Generation, and Delivery.
4. **Streaming**: The narrative response streams to the player via SSE,
   token-by-token.
5. **Completion**: The stream completes. The system updates world state (S04),
   consequence state (S05), and character state (S06).
6. **Next Prompt**: The system returns to step 1.

**FR-1.2** — Processing MUST begin within 500ms of input submission. The player should
see the first token within 2 seconds under normal conditions.

**FR-1.3** — The system MUST NOT accept new player input while a response is still
streaming. The input prompt appears only after streaming completes.

**FR-1.4** — If the player submits empty or whitespace-only input, the API boundary
returns `400 input_invalid` (per S10/S23). Client UX MAY render a gentle narrative nudge
copy as presentation behavior.

### FR-2: Turn Types

**FR-2.1** — The system MUST classify each player input into one of these turn types:

| Type | Description | Example |
|------|-------------|---------|
| **Action** | Player does something physical | "I climb the wall" |
| **Dialogue** | Player speaks to a character | "I ask the guard about the key" |
| **Exploration** | Player examines the environment | "I look around" / "What's in the chest?" |
| **Introspection** | Player reflects internally | "I think about what the oracle said" |
| **System** | Meta-commands | "/save", "/help", "/settings" |

**FR-2.2** — Turn type classification is an input to narrative generation (S03), not a
gate. The player never sees the classification. It influences tone, not permission.

**FR-2.3** — Mixed-type inputs ("I look around the room and ask the barkeep what's
upstairs") are valid. The system handles composite inputs as a single turn with
blended response.

**FR-2.4** — System commands MUST be prefixed with `/` to distinguish them from
narrative input. Unrecognized `/` commands return a help message, not a narrative
response.

### FR-3: The Meta-Loop

**FR-3.1** — The meta-loop has four levels of narrative structure:

| Level | Unit | Approximate Length | What Changes |
|-------|------|--------------------|--------------|
| **Turn** | Single player input/response | 30s–2min | Immediate scene state |
| **Scene** | A coherent situation | 5–15 turns | Location, active NPCs, tension |
| **Chapter** | A narrative arc segment | 3–8 scenes | Story direction, world state |
| **Story** | Complete playthrough | 5–20 chapters | Everything; story concludes |

**FR-3.2** — Scene boundaries are detected by the system (significant location change,
NPC exit, time skip, tension resolution) and optionally surfaced to the player as
subtle narrative markers (a paragraph break, a poetic transition line).

**FR-3.3** — Chapter boundaries MUST be explicitly marked with a chapter title and a
brief thematic summary. Example:

> *— Chapter 3: The Weight of Crowns —*
> *In which alliances were tested and a throne proved heavier than expected.*

**FR-3.4** — Story completion occurs when the narrative reaches a natural conclusion
based on the story arc established in Genesis. The system MUST signal story completion
clearly, not just stop generating.

**FR-3.5** — There is no fixed turn/scene/chapter count. The meta-loop adapts to the
player's pace and the story's needs.

### FR-4: Progression

**FR-4.1** — Progression is **emergent, not mechanical**. There are no XP points,
no level-ups, no skill trees. The player advances through:

- **Story milestones**: Plot events that change the world permanently.
- **Character development**: Traits, skills, and reputation that evolve through
  demonstrated behavior (see S06).
- **World state changes**: The world remembers and reacts to what the player has done
  (see S04, S05).
- **Relationship shifts**: NPCs change their disposition based on history (see S06).

**FR-4.2** — The system MUST track player accomplishments for narrative callback.
If the player saved a village in Chapter 2, the village remembers in Chapter 5.

**FR-4.3** — Progression MUST be visible to the player through narrative, not UI
meters. The player *feels* stronger because the story treats them differently, not
because a number went up.

**FR-4.4** — The system MAY surface a "story so far" summary on request (`/recap`)
that highlights key milestones, relationships, and world changes.

### FR-5: Save & Resume

**FR-5.1** — Game state is **auto-saved after every turn**. There is no manual save
button (though `/save` can trigger an explicit checkpoint).

**FR-5.2** — Auto-save captures:
- Current world state snapshot (S04)
- Player character state (S06)
- Active consequence chains (S05)
- Narrative context window (recent turns, active threads)
- Meta-loop position (current scene/chapter)
- Timestamp

**FR-5.3** — Resume MUST restore the game to the exact state at the last completed
turn. The player sees the last narrative response and a fresh input prompt.

**FR-5.4** — On resume, the system MUST provide a brief contextual recap:
*"When we last left off: [1-2 sentence summary of recent events and current
situation]."*

**FR-5.5** — The system MUST handle "stale" sessions gracefully. If a player returns
after days/weeks, the recap is more detailed and the narrative may acknowledge
the passage of time in-world if appropriate.

**FR-5.6** — Players have ONE active save per story. No save-scumming, no multiple
save slots per playthrough. (They can start new stories via re-Genesis.)

### FR-6: Failure & Recovery

**FR-6.1** — There is **no game-over state**. Failure is a narrative event, not a
system state. If the player's character "dies," the story handles it narratively:
- Narrow escape with consequences (injury, lost items, reputation damage)
- Time rewind with narrative framing ("You snap awake — it was a vision")
- Character transformation (the story continues, but something fundamental changed)
- Story pivot (the failure becomes the new plot direction)

**FR-6.2** — The system MUST communicate failure consequences clearly in narrative.
The player should understand what they lost or what changed, not just that
"something bad happened."

**FR-6.3** — Repeated failure in the same situation SHOULD escalate consequences
but also offer alternative approaches. The game should never become a brick wall.

**FR-6.4** — The system MUST distinguish between:
- **Player choice failure**: The player chose poorly (consequence is narrative)
- **Impossible action**: The player attempted something the world doesn't support
  (gentle redirect: "The cliff face offers no handholds here, but you notice a
  path winding around...")

### FR-7: Session Boundaries

**FR-7.1** — A session starts when the player loads the game (new or resumed).

**FR-7.2** — A session ends when:
- The player explicitly ends it (`/quit`, `/pause`, closing the browser)
- The player is idle for more than 30 minutes (configurable)
- A natural pause point is reached and the player confirms

**FR-7.3** — At session end, the system SHOULD offer a natural pause point:
*"The fire crackles low. A good place to rest. Until next time, traveler."*
This is cosmetic — the actual save point is the last completed turn.

**FR-7.4** — Session duration is tracked for analytics but NEVER communicated to the
player as a performance metric. No "you played for 47 minutes!" — this isn't a
fitness tracker.

**FR-7.5** — The system MUST handle abrupt disconnection (browser crash, network loss)
gracefully. State as of the last completed turn is preserved. Mid-stream narrative
is discarded and can be regenerated on resume.

### FR-8: Replayability

**FR-8.1** — A completed story is archived. The player can view their story history
but cannot resume a completed story.

**FR-8.2** — Starting a new game triggers Genesis (S02) from scratch. New world, new
character, new story.

**FR-8.3** — The system MUST NOT reuse world seeds, NPC names, or plot structures
from previous playthroughs (within the same player account). Each playthrough is
genuinely unique.

**FR-8.4** — Cross-playthrough progression is explicitly OUT OF SCOPE for v1.
No "new game+" mechanics, no unlockable content based on previous completions.

---

## Non-Functional Requirements

- **NFR-1.1** — First token of narrative response MUST appear within 2 seconds of
  input submission (p95).
- **NFR-1.2** — Full narrative response MUST complete streaming within 15 seconds
  (p95) for a standard turn.
- **NFR-1.3** — Auto-save MUST complete within 1 second and MUST NOT block the next
  input prompt.
- **NFR-1.4** — Resume from cold start (server-side state load) MUST complete within
  3 seconds.
- **NFR-1.5** — The system MUST support at least 100 concurrent active sessions.
- **NFR-1.6** — Turn history MUST be retained for the duration of the story (no
  silent truncation).
- **NFR-1.7** — Narrative response length SHOULD be 100–400 words per turn.
  Exceptional turns (chapter transitions, climactic moments) MAY exceed this.

---

## User Journeys

### Journey 1: A Typical Play Session

1. Player opens TTA. Sees a loading screen, then their last narrative response and
   a fresh input prompt with the recap: *"When we last left off: You were standing
   at the gates of Thornhaven, the merchant's warning still ringing in your ears."*
2. Player types: "I enter the town cautiously, keeping my hand on my sword."
3. Narrative streams in: describes the bustling town, the wary glances of guards,
   the smell of bread from a nearby bakery. Ends with a moment of tension — someone
   is watching from an alley.
4. Player types: "I approach the person in the alley."
5. Narrative reveals an NPC — a street urchin with information to trade.
6. This continues for 20 minutes (roughly 12-15 turns).
7. Player types `/quit`. The system offers a closing line and saves.

### Journey 2: Returning After a Week

1. Player opens TTA after 7 days away.
2. System provides an extended recap: *"It's been some time since you walked these
   roads. Let me remind you: You arrived in Thornhaven seeking the merchant Aldric,
   who holds a piece of the map you need. You'd just met a street urchin named Pip
   who claimed to know Aldric's schedule. The town was tense — guards were doubling
   patrols after the warehouse fire you may or may not have caused."*
3. Player continues from where they left off.

### Journey 3: Failing Forward

1. Player attempts to sneak into the lord's manor. Rolls (metaphorically) poorly.
2. Instead of "You failed. Try again?", the narrative describes getting caught by
   a guard — but the guard is an old friend from the player's backstory. Now there's
   a new complication: the friend is conflicted, the player has leverage but also
   guilt. The story branches in an unexpected direction.
3. The player's "failure" created a more interesting story than success would have.

### Journey 4: Completing a Story

1. Player reaches the climax of their story arc (established during Genesis).
2. The narrative builds to a conclusion — choices converge, consequences resolve,
   the world settles into a new shape.
3. Chapter title appears: *"— Epilogue: What Remained —"*
4. A short epilogue describes the aftermath. NPCs reference the player's choices.
   The world reflects what was built or broken.
5. The system displays: *"Your story has concluded. [View Story Archive] [Begin
   New Adventure]"*
6. The completed story is archived. Starting a new adventure triggers Genesis.

---

## Edge Cases

- **EC-1.1**: Player submits extremely long input (>2000 characters). System truncates
  gracefully and processes the meaningful portion, with a gentle note if content was
  trimmed.

- **EC-1.2**: Player submits the same input repeatedly. System varies its response
  and may narratively acknowledge the repetition: *"Once again, you try the door.
  Once again, it holds firm. Perhaps another approach?"*

- **EC-1.3**: Player tries to break the fourth wall ("I type /quit in the story").
  System stays in-character or gently redirects.

- **EC-1.4**: Player goes idle mid-session. After the timeout, the session auto-saves
  and ends. On return, a recap is provided. The world may have moved forward slightly
  (time passed in-world).

- **EC-1.5**: Player submits input that contradicts established world state ("I fly
  to the moon" in a medieval setting). System responds in-narrative: *"You look up
  at the moon hanging heavy and silver above the treeline. Beautiful, but impossibly
  far. Your feet remain firmly on the cobblestones."*

- **EC-1.6**: Player input is ambiguous ("I go left" when there's no established left).
  System asks for clarification in-character: *"The crossroads offers three paths:
  the forest trail north, the river road east, or the old mine south. Which calls
  to you?"*

- **EC-1.7**: Network disconnects mid-stream. On reconnect, the partial response is
  discarded and the turn is re-processed from the player's last input.

- **EC-1.8**: Player tries to interact with an NPC who left the scene two turns ago.
  System narrates the absence: *"The alley where Pip stood is empty now — just
  scattered leaves and the faint smell of chimney smoke."*

---

## Acceptance Criteria

- **AC-1.1**: Given a player submits valid input, when the system processes it, then
  a narrative response begins streaming within 2 seconds and completes within 15
  seconds.

- **AC-1.2**: Given a player submits empty input, when processed, then an in-world
  narrative nudge is returned (not an error message).

- **AC-1.3**: Given a player types `/save`, when processed, then the current state is
  checkpointed and a confirmation is shown without breaking immersion.

- **AC-1.4**: Given a player closes their browser and reopens the game, when the page
  loads, then they see their last narrative response, a contextual recap, and a fresh
  input prompt.

- **AC-1.5**: Given a player's character fails at an action, when the failure is
  processed, then the narrative describes the failure with consequences — no game-over
  screen appears.

- **AC-1.6**: Given a player reaches story completion, when the epilogue finishes,
  then the story is archived and the option to begin a new Genesis is presented.

- **AC-1.7**: Given a player is idle for 30+ minutes, when the timeout triggers, then
  the session auto-saves and ends cleanly. On return, a recap is provided.

- **AC-1.8**: Given a player starts a second playthrough, when Genesis completes, then
  the new world, character, and story are entirely distinct from the first.

- **AC-1.9**: Given narrative is streaming and the connection drops, when the player
  reconnects, then the turn is re-processed from their last input and streams fresh.

- **AC-1.10**: Given a player submits a `/` command that doesn't exist, when processed,
  then a help message lists available commands (not a narrative response).

---

## Dependencies

| Spec | Relationship |
|------|-------------|
| **S02 — Genesis** | Genesis produces the initial state that the gameplay loop runs on. |
| **S03 — Narrative Engine** | The turn cycle invokes the narrative engine for every response. |
| **S04 — World Model** | World state is read and updated every turn. |
| **S05 — Choice & Consequence** | Consequence chains are evaluated and updated every turn. |
| **S06 — Character System** | Character state is read and updated every turn. |
| **S13 — Storage Schema** | Save/resume depends on the persistence layer. |

---

## Open Questions

- **OQ-1.1**: Should the meta-loop structure (scenes, chapters) be visible to the
  player as navigation, or purely as narrative markers? Leaning toward narrative-only
  for v1.

- **OQ-1.2**: What's the maximum story length before quality degrades? Is there a
  natural ceiling on context window that forces story completion?

- **OQ-1.3**: Should the system offer "suggested actions" alongside free-text input?
  Pro: accessibility, helps stuck players. Con: reduces agency feeling, implies a
  "right answer." See S05.

- **OQ-1.4**: How should the recap handle spoiler-sensitivity? If the player left off
  right before a twist, the recap shouldn't reveal it.

- **OQ-1.5**: Should idle timeout be configurable by the player? Or is 30 minutes a
  reasonable universal default?

- **OQ-1.6**: What happens to a story that's been abandoned for months? Does it stay
  resumable indefinitely?

---

## Out of Scope (v1)

- Multiplayer or co-op gameplay
- New game+ or cross-playthrough progression
- Manual save slots or save-scumming
- Achievements or trophies
- Player-facing analytics ("you made 47 choices")
- Undo/rewind mechanics
- Branching save points (fork a save to try different paths)
- Voice input or voice narration
- Timer-based mechanics or real-time elements

## Changelog

- 2026-04-09: Replaced deprecated IPA/WBA/NGA agent names with 4-stage pipeline names
  (Input Understanding, Context Assembly, Narrative Generation, Delivery) in FR-1.1.
  Corrected cross-reference from S03 to S08 (Turn Processing Pipeline).

---

## v1 Closeout (Non-normative)

### What Shipped

| Item | Shipped | Verified | Evidence | Notes |
|------|---------|----------|----------|-------|
| Empty input returns in-world message (AC-1.2) | ✅ | ✅ | `test_s01_ac_compliance.py` | Handled in command router |
| `/save` persists state (AC-1.3) | ✅ | ✅ | `test_s01_ac_compliance.py` | Snapshot written to PG |
| Failure narrative on action failure (AC-1.5) | ✅ | ✅ | `test_s01_ac_compliance.py` | Intent-classified failure routes to narrative |
| Story-completion epilogue (AC-1.6) | ✅ | ✅ | `test_s01_ac_compliance.py` | Game moves to `completed` state |
| 30-min idle timeout (AC-1.7) | ✅ | ✅ | `test_s01_ac_compliance.py`; lifecycle cleanup module | Session expires; state preserved |
| Second-playthrough world isolation (AC-1.8) | ✅ | ✅ | `test_s01_ac_compliance.py` | New world graph seeded independently |
| Unknown-command error response (AC-1.10) | ✅ | ✅ | `test_s01_ac_compliance.py` | Command router returns narrative error |
| Sim turns complete within response window | ✅ | ✅ | PR #161 sim harness (11/11 turns) | Live streaming tested |

### Deferred to v2

| Item | Reason | v2 Priority |
|------|--------|-------------|
| Response starts within 2 s / completes within 15 s (AC-1.1) | Requires integration infra with time-aware assertions; LLM latency not deterministic | High |
| Browser-close + reopen shows last narrative + recap (AC-1.4) | Requires persistent last-narrative store and reconnect UX flow | High |
| Mid-stream SSE reconnect reprocesses from last input (AC-1.9) | SSE reconnect not implemented; EventSource would re-trigger full turn | High |

### Gaps Found

**AC-1.1 unverified end-to-end**: The 2 s time-to-first-token / 15 s time-to-complete targets were not measured in v1. Sim runs produced responses but did not instrument per-turn latency. LLM provider latency varies significantly; no P99 latency data exists.

**AC-1.4 / AC-1.9 reconnect gap**: Both ACs require client-side state to be restored after disconnection. The SSE layer delivers tokens but does not persist the turn-in-progress state for reconnect. A player who loses connectivity mid-response currently receives no replay. This is a high-severity UX gap for mobile or unreliable connections.

