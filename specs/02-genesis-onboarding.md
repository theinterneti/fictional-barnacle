# S02 — Genesis Onboarding

> **Status**: 📝 Draft
> **Level**: 1 — Core Game Experience
> **Dependencies**: S00
> **Last Updated**: 2025-07-24

---

## Purpose

Genesis is the first thing every player experiences. It is not a form. It is not a
character creator with slider bars. It is a *narrative experience* that simultaneously
introduces the player to TTA's interaction model and generates the unique world and
character they'll inhabit.

By the end of Genesis, the player should feel:
1. They understand how to play (type things, things happen).
2. Their world exists because of *their* choices — it's not a premade map.
3. Their character is *theirs* — not a template, not an avatar, a person they shaped
   through story.
4. They are *already playing* — Genesis doesn't end, it transforms into gameplay.

The old TTA Genesis had 5 acts: Building World → Slip Phase → Building Character →
First Light → The Becoming. This is a solid skeleton. We question the details, not
the bones.

---

## User Stories

### First-Time Experience

- **US-2.1**: As a first-time player, I want the game to start with a compelling
  narrative moment (not a menu), so that I'm hooked from the first sentence.

- **US-2.2**: As a first-time player, I want to understand how to play *by playing*,
  not by reading a tutorial, so that learning feels natural.

- **US-2.3**: As a first-time player, I want my early choices to feel meaningful even
  before I understand the full game, so that I'm invested from the start.

### World Creation

- **US-2.4**: As a player, I want my world to emerge from my choices — not from
  checking boxes — so that it feels like *my* world.

- **US-2.5**: As a player, I want to influence the tone, genre, and scale of my world
  without being asked "pick a genre" directly, so that the process feels organic.

- **US-2.6**: As a player, I want to be surprised by my own world — I give hints, and
  the system creates something richer than I imagined.

### Character Creation

- **US-2.7**: As a player, I want my character to emerge from the story — from how I
  react to situations — not from allocating stat points.

- **US-2.8**: As a player, I want to name my character at a moment that feels right in
  the narrative, not on a form before the story starts.

- **US-2.9**: As a player, I want to see my character reflected back to me — a moment
  where the narrative shows me who I've become — so that the character feels real.

### Transition to Gameplay

- **US-2.10**: As a player, I want the shift from "creation" to "playing" to feel
  seamless — no loading screen, no "Genesis Complete!" banner. I'm just... playing.

- **US-2.11**: As a player, I want the world and character I created to immediately
  matter in the first "real" turn — the story should reference what I built.

### Return Players

- **US-2.12**: As a returning player starting fresh, I want Genesis to feel new — not
  repetitive — even if I've done it before.

- **US-2.13**: As a returning player, I want Genesis to be no longer than 10 minutes,
  so I can get to gameplay quickly.

---

## Functional Requirements

### FR-1: Act Structure

Genesis follows a **5-act structure**. Each act is a short narrative sequence (2-4
player interactions) that generates a specific layer of the game state.

**FR-1.1** — Act I: The Void (World Seeding)

*"Before anything, there is nothing. And then — a question."*

- The system presents an evocative opening that establishes Genesis as a creation myth.
- Through 2-3 narrative prompts, the player makes choices that seed the **WorldSeed**
  parameters (see FR-2).
- The player does NOT see the parameters. They answer questions like:
  - *"In the darkness, something stirs. Is it the hum of machines, the whisper of
    ancient words, or the crash of waves?"* → seeds `tech_level` / `magic_presence`
  - *"A light appears — vast and blinding, or small and flickering?"* → seeds
    `world_scale`
- Act I should feel mysterious, primal, evocative. 1-2 minutes.

**FR-1.2** — Act II: The Shaping (World Building)

*"The world takes form around you."*

- The system uses the WorldSeed to generate an initial world description.
- The player interacts with the emerging world through 2-3 prompts that refine it:
  - *"The ground beneath you — is it stone smoothed by centuries, soft earth after
    rain, or metal grating?"* → refines terrain/setting
  - *"Voices carry on the wind. Many, speaking over each other? Or one, calling
    to you alone?"* → refines `player_position` (populated vs. isolated)
- By the end of Act II, the world has a geography, a tone, and a first location.
- 1-2 minutes.

**FR-1.3** — Act III: The Stranger (Character Emergence)

*"You are here now. But who are you?"*

- The system places the player *in* the world and presents a situation that requires
  response. The response reveals character.
- Instead of "choose a class," the player faces a scenario:
  - A figure approaches. How do you react? → reveals temperament
  - You find something valuable that belongs to someone else. What do you do? →
    reveals moral alignment
  - Someone asks for your name. → the player names their character
- The system infers character traits from behavior, not from selection.
- 2-3 minutes.

**FR-1.4** — Act IV: The Ripple (World Reacts to Character)

*"The world has noticed you."*

- The world responds to who the player has shown themselves to be.
- NPCs react to the player's demonstrated traits. The environment shifts subtly.
- This act establishes the player's starting position in the world's social/political
  fabric.
- At least one meaningful NPC interaction occurs — someone who will recur.
- 1-2 minutes.

**FR-1.5** — Act V: The Threshold (Transition to Gameplay)

*"And so it begins."*

- A narrative hook emerges — a question, a threat, a mystery, an opportunity — that
  becomes the player's initial story arc.
- The hook references choices from Acts I-IV. It feels inevitable, not random.
- The act ends with the player standing at the start of their adventure, input prompt
  ready. They are now *playing*.
- The transition is **seamless**. No "Genesis Complete" message. No loading screen.
  The player's next input is their first gameplay turn.
- 1-2 minutes.

**FR-1.6** — Total Genesis duration MUST be 5-10 minutes for a player who engages
at a moderate pace. Under 5 minutes if they're terse. Never more than 12 minutes.

**FR-1.7** — Each act MUST have a minimum of 2 player interactions. No act is a
non-interactive cutscene.

### FR-2: WorldSeed

**FR-2.1** — The WorldSeed is a structured object generated during Acts I and II. It
contains the parameters from which the full world is generated:

| Parameter | Description | Example Values |
|-----------|-------------|----------------|
| `tone` | Emotional register of the world | dark, hopeful, whimsical, austere |
| `tech_level` | Technology sophistication | primitive, medieval, industrial, futuristic |
| `magic_presence` | Prevalence of the supernatural | none, rare, common, pervasive |
| `world_scale` | Size and scope | intimate (one town), regional, continental, cosmic |
| `player_position` | Social starting point | outsider, local, authority, fugitive |
| `power_source` | What drives conflict | political, natural, magical, technological |
| `defining_detail` | One specific, vivid detail | "the sky is always amber," "all water glows faintly" |

**FR-2.2** — WorldSeed parameters are **inferred from player choices**, not selected
from menus. The player never sees the parameter names.

**FR-2.3** — The system MAY combine or interpolate parameters. A player whose choices
suggest both high tech and high magic gets a magitech world, not an error.

**FR-2.4** — WorldSeed MUST be persisted. It is the genetic code of the world —
referenced by the narrative engine (S03) for tone consistency and by the world model
(S04) for generation rules.

**FR-2.5** — No two Genesis runs with different player choices should produce the same
WorldSeed (within practical uniqueness — exact parameter value combinations may recur,
but the `defining_detail` adds a unique stamp).

### FR-3: Character Creation

**FR-3.1** — The player character (PC) is defined by:
- **Name**: Provided by the player during Act III.
- **Traits**: 2-4 personality/behavioral traits inferred from choices (e.g., "cautious,"
  "compassionate," "defiant"). See S06 for trait system.
- **Background sketch**: A 1-2 sentence backstory generated from Act III/IV choices.
- **Starting capabilities**: What the character can do, inferred from demonstrated
  behavior (not from class selection).

**FR-3.2** — The system MUST confirm the character back to the player before Act V
concludes. This is a "mirror moment":
*"You catch your reflection in a rain puddle — [name], the [trait] [trait] soul
who [background sketch]."*

**FR-3.3** — The player MUST have the opportunity to adjust if the mirror moment feels
wrong. A simple prompt: *"Is this who you are? Or is there something else beneath
the surface?"* allows the player to correct or refine.

**FR-3.4** — Character creation MUST NOT require the player to have genre knowledge.
A player who knows nothing about fantasy should be able to create a compelling
character in a fantasy world.

### FR-4: Transition to Gameplay

**FR-4.1** — The transition from Genesis to gameplay is **invisible to the player**.
There is no screen change, no loading indicator, no "you are now playing" message.

**FR-4.2** — The first gameplay turn MUST reference at least two elements established
during Genesis (a location, an NPC, a character trait, a world detail).

**FR-4.3** — The initial story hook (from Act V) becomes the first chapter's driving
question. It should be open enough to support multiple approaches but specific enough
to give direction.

**FR-4.4** — If the player's first gameplay input ignores the story hook entirely
(e.g., "I walk the other way"), the system adapts. The hook follows or transforms.
The world is responsive, not a railroad.

### FR-5: Replayability

**FR-5.1** — A player can trigger Genesis at any time by choosing "New Adventure" from
their dashboard (after completing or abandoning a current story).

**FR-5.2** — Re-Genesis MUST NOT repeat the same opening prompts verbatim. The system
has multiple phrasings for each seed question. A returning player should feel like
they're experiencing a new creation myth, not re-reading the old one.

**FR-5.3** — The system MUST NOT reference previous playthroughs during Genesis. Each
Genesis is a clean slate. No "welcome back" or "last time you..."

**FR-5.4** — WorldSeed parameters from previous playthroughs are available to the
system for *de-duplication* purposes (avoid generating the same world) but MUST NOT
influence the current Genesis narratively.

### FR-6: Solo vs. Guided

**FR-6.1** — Genesis is **guided by default**. The AI leads the player through the
five acts with narrative prompts. The player responds freely.

**FR-6.2** — A player who gives very short responses ("yes", "the first one", "idk")
gets more guidance — richer descriptions, clearer prompts, more scaffolding.

**FR-6.3** — A player who gives rich, detailed responses gets less scaffolding —
the system incorporates their details directly and moves faster.

**FR-6.4** — The system MUST NOT allow the player to "skip" Genesis entirely. The
minimum path through Genesis requires at least 8 player inputs.

---

## Non-Functional Requirements

- **NFR-2.1** — Genesis MUST complete in 5-10 minutes for a moderately-paced player.
- **NFR-2.2** — Each Genesis prompt MUST stream the first token within 2 seconds.
- **NFR-2.3** — WorldSeed generation MUST complete within 3 seconds of Act II
  conclusion.
- **NFR-2.4** — The full world state produced by Genesis MUST be persisted before
  Act V begins (the player must never lose their created world to a mid-Genesis
  crash).
- **NFR-2.5** — Genesis MUST work on mobile browsers (touch input, responsive layout).
- **NFR-2.6** — Genesis content MUST be safe for all ages — no graphic violence, no
  sexual content, no real-world trauma triggers during world creation. (The world
  *itself* may be dark; the creation process is gentle.)

---

## User Journeys

### Journey 1: First-Time Player (Fantasy World)

1. Player opens TTA for the first time. No menu — the screen is dark.
2. Text fades in: *"Before the beginning, there is silence. And in the silence,
   a question."*
3. *"In the darkness, something stirs. What do you hear?"*
4. Player types: "Whispers, like pages turning in an old library."
5. System infers: magical world, intellectual tone. Responds: *"The whispers coalesce
   — words in languages older than memory. The darkness thins, and you feel the weight
   of countless stories pressing against the veil between nothing and something."*
6. *"A light appears — describe it."*
7. Player types: "A single candle flame, impossibly bright."
8. System infers: intimate scale, focused world. Begins generating world: a vast
   library-city, candle-lit, where knowledge is currency.
9. [Acts II-IV proceed — world refines, character emerges from reactions to library
   scenarios, NPCs are librarians and seekers and banned-book smugglers]
10. Act V: The player stands at the entrance to a restricted section, a torn page
    in their hand, a librarian watching them with suspicion. The first chapter begins.

### Journey 2: Returning Player (Sci-Fi World)

1. Player completed a fantasy story. Starts "New Adventure."
2. Genesis opens differently: *"The void hums. Not silence this time — static. The
   universe remembers how to be, and begins."*
3. Prompts explore different axes: *"The hum sharpens into a signal. Is it a distress
   call, a broadcast, or a countdown?"*
4. Player types: "A countdown. Something is running out of time."
5. System generates: urgent, sci-fi, ticking-clock world. Tension from the start.
6. Character emerges through crisis responses, not contemplation.
7. Genesis completes in 7 minutes. Player is on a space station with a failing reactor
   and a crew that doesn't trust them.

### Journey 3: Terse Player

1. Player gives minimal responses: "magic," "big," "I don't know."
2. System provides richer scaffolding: *"Magic it is — but what kind? The world offers
   you three visions: a forest where the trees sing, a city where the streets rearrange
   themselves, or a mountain whose peak touches a second sky. Which calls to you?"*
3. Player picks: "The city."
4. System builds from there. Genesis takes slightly longer but still completes under
   10 minutes. The character has fewer specific traits but a clear archetype.

### Journey 4: Verbose Player

1. Player types paragraphs: "I hear a mechanical heartbeat — like a giant clockwork
   engine buried deep underground, and it's been running for centuries, and the people
   on the surface have forgotten it's there, but it's starting to slow down..."
2. System absorbs the detail directly. The world is *exactly that*. System confirms:
   *"Yes — the Heart of the Under-Engine beats beneath the city of Verrada, its rhythm
   so constant that the citizens mistake it for the pulse of the earth itself. But
   lately, the rhythm has... stuttered."*
3. Genesis moves faster. Fewer prompts needed. Completes in 6 minutes.

---

## Edge Cases

- **EC-2.1**: Player tries to create an offensive or harmful world ("I want a world
  where [harmful content]"). System redirects: *"The void considers your words, but
  some shapes refuse to form. Perhaps something else stirs in the darkness?"*
  WorldSeed parameters are not set from harmful input.

- **EC-2.2**: Player disconnects mid-Genesis. On return, Genesis resumes from the last
  completed act. Partial act state is discarded — the act replays from the beginning
  with fresh prompts.

- **EC-2.3**: Player gives contradictory answers (high tech in Act I, primitive in
  Act II). System reconciles narratively: *"The ruins speak of a civilization that
  once touched the stars — but that was long ago. Now, the machines sleep, and the
  people have learned simpler ways."* (Post-apocalyptic blend.)

- **EC-2.4**: Player tries to skip ahead ("Can we just start the game?"). System
  acknowledges but explains within narrative: *"Soon. The world needs one more
  moment to find its shape."* Minimum interaction count is enforced.

- **EC-2.5**: Player names their character something offensive. System applies content
  filter and gently asks for another name in-narrative: *"The name echoes strangely
  here, as if the world can't quite hold it. Perhaps you're known by another name
  in this place?"*

- **EC-2.6**: Player names their character something extremely long (50+ characters).
  System accepts a display-truncated version and uses a short form in narrative.

- **EC-2.7**: Two players, same account, run Genesis simultaneously. System prevents
  concurrent Genesis sessions — only one active Genesis per account.

- **EC-2.8**: Player creates a world identical (by chance) to a previous player's.
  This is fine — WorldSeed uniqueness is per-player, not global.

---

## Acceptance Criteria

- **AC-2.1**: Given a new player opens TTA, when the app loads, then Genesis begins
  with a narrative prompt — no menu, no tutorial screen.

- **AC-2.2**: Given a player completes all five acts of Genesis, when Act V concludes,
  then a valid WorldSeed, character profile, initial world state, and story hook are
  persisted to the database.

- **AC-2.3**: Given a player completes Genesis, when they submit their first post-
  Genesis input, then the narrative response references at least two Genesis-
  established elements.

- **AC-2.4**: Given a moderately-paced player (10-30 second response times), when
  they complete Genesis, then the total elapsed time is between 5 and 10 minutes.

- **AC-2.5**: Given a player disconnects during Act III, when they reconnect, then
  Genesis resumes from the beginning of Act III (not Act I, not mid-Act-III).

- **AC-2.6**: Given a player has completed one playthrough and starts a new Genesis,
  when the opening prompts appear, then they are phrased differently from the
  player's previous Genesis experience.

- **AC-2.7**: Given a player provides harmful content during Genesis, when the input
  is processed, then the system redirects without generating harmful world content
  and without displaying an error.

- **AC-2.8**: Given a terse player who responds with single words, when Genesis
  completes, then a valid and coherent world and character are still generated.

- **AC-2.9**: Given a player says "Is this who you are?" and responds "No, I'm
  actually more aggressive," when processed, then the character traits are adjusted
  to reflect the correction.

- **AC-2.10**: Given Genesis completes, when the player looks at the experience in
  hindsight, then there is no visible "creation mode ended" boundary — the story
  simply *continued*.

---

## Dependencies

| Spec | Relationship |
|------|-------------|
| **S01 — Gameplay Loop** | Genesis produces the initial state that the gameplay loop runs on. |
| **S03 — Narrative Engine** | Genesis uses the narrative engine for all its prose. |
| **S04 — World Model** | Genesis generates the initial world model from the WorldSeed. |
| **S05 — Choice & Consequence** | Genesis choices are the first entries in consequence tracking. |
| **S06 — Character System** | Genesis creates the initial player character. |
| **S13 — Storage Schema** | Genesis state must be persisted across its acts. |

---

## Open Questions

- **OQ-2.1**: Should the 5-act structure be rigid (always exactly 5 acts) or adaptive
  (3-7 acts depending on player engagement)? Leaning rigid for v1 consistency.

- **OQ-2.2**: How much world detail should Genesis generate vs. defer to lazy
  generation during gameplay? Genesis should create the seed, not the entire atlas.

- **OQ-2.3**: Should there be a "Quick Genesis" for returning players who want to
  skip the ceremony? Concern: it undermines the design philosophy. Maybe shorter,
  not skippable.

- **OQ-2.4**: Can the "mirror moment" (character confirmation) feel natural and not
  like a form review? The wording needs to be crafted carefully.

- **OQ-2.5**: How do we handle the WorldSeed `defining_detail` if the player doesn't
  provide one organically? Does the system invent one? Is that okay?

- **OQ-2.6**: Should Genesis generate the story's *ending* (thematically) as well
  as its beginning? Knowing the destination could help the narrative engine build
  toward it, but might constrain emergent storytelling.

---

## Out of Scope (v1)

- Multiplayer Genesis (co-creating a world with another player)
- World templates ("Quick start: Medieval Fantasy")
- Importing worlds from other systems
- AI-generated visual art during Genesis
- Voice-guided Genesis
- Player-specified content ratings (the system decides appropriate content)
- Genesis replay within the same story (re-building mid-game)
