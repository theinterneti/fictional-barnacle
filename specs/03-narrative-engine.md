# S03 — Narrative Engine

> **Status**: 📝 Draft
> **Level**: 1 — Core Game Experience
> **Dependencies**: S00
> **Last Updated**: 2025-07-24

---

## Purpose

The narrative engine is the voice of TTA. It turns structured game state into prose
that makes the player feel something. It is the difference between "You enter a room.
There is a table." and "The door groans open onto a room that smells of old paper
and regret. A table dominates the center — scarred, heavy, and bearing a single
envelope addressed to no one."

This spec defines *what the engine produces*, not *how it produces it*. The engine
must be consistent, surprising, genre-flexible, and fast. It must maintain a coherent
narrator voice across hundreds of turns while never feeling repetitive. It is the
hardest problem in TTA, and the most important.

---

## User Stories

### Narrative Quality

- **US-3.1**: As a player, I want every narrative response to feel crafted — not
  generic AI slop — so that I stay immersed and want to keep reading.

- **US-3.2**: As a player, I want the narrator's voice to feel consistent throughout
  my story — same tone, same personality — so that the world feels authored, not
  randomly generated.

- **US-3.3**: As a player, I want to be surprised. I don't want to predict every
  response. The world should do things I didn't expect but that make sense in
  retrospect.

### Coherence

- **US-3.4**: As a player, I want the story to remember everything important. If I
  gave a sword to an NPC ten turns ago, that NPC should have the sword now.

- **US-3.5**: As a player, I want the world to be internally consistent. If it's
  winter in turn 5, it shouldn't be summer in turn 6 (unless time passed).

- **US-3.6**: As a player, I want the narrative to build on itself — callbacks to
  earlier events, foreshadowing, running themes — not just isolated turn responses.

### Delivery

- **US-3.7**: As a player, I want narrative to stream in smoothly, word by word, so
  that reading feels like the story is being told to me in real time.

- **US-3.8**: As a player, I want the response length to match the moment — short and
  punchy for action, longer and more descriptive for exploration or emotional beats.

### Pacing

- **US-3.9**: As a player, I want the story to have rhythm — tension followed by
  release, action followed by reflection — not constant high-intensity or monotony.

- **US-3.10**: As a player, I want quiet moments to feel earned, not like the system
  ran out of ideas.

### Genre

- **US-3.11**: As a player, I want the narrative voice to match my world's genre.
  A cyberpunk world should feel different from a pastoral fantasy. The engine should
  adapt, not apply one voice to all worlds.

---

## Functional Requirements

### FR-1: Narrator Voice

**FR-1.1** — The default narrator perspective is **second person, present tense**.
*"You push open the door. The room beyond is dark."*

**FR-1.2** — The narrator voice has three tunable dimensions, set during Genesis and
consistent throughout a playthrough:

| Dimension | Spectrum | Example Low | Example High |
|-----------|----------|-------------|--------------|
| **Formality** | Casual ↔ Literary | "You check the door. Locked." | "Your fingers find the lock's cold refusal." |
| **Warmth** | Detached ↔ Intimate | "The village burns." | "The village burns, and something in your chest burns with it." |
| **Humor** | Serious ↔ Playful | "The guard questions you." | "The guard questions you with the enthusiasm of a man who peaked in guard school." |

**FR-1.3** — The narrator voice is influenced by the WorldSeed `tone` parameter and
refined through the player's engagement style during Genesis.

**FR-1.4** — The narrator MUST NOT:
- Break the fourth wall (no "as a text adventure game...")
- Reference AI, language models, or generation
- Use modern slang in non-modern settings
- Explain game mechanics in narrator voice
- Address the player as "the player"

**FR-1.5** — The narrator MAY occasionally address the character directly as "you"
in a more intimate way during emotional moments, as if the narrator knows the
character personally. This is a stylistic flourish, not a rule violation.

### FR-2: Coherence Management

**FR-2.1** — Every narrative generation call receives a **context assembly** that
includes:

| Context Layer | Content | Max Size (Approx.) |
|---------------|---------|-------------------|
| **World State** | Current location, time, weather, active entities | Structured data |
| **Character State** | PC traits, inventory, active conditions, reputation | Structured data |
| **Relationship State** | Active NPC dispositions and recent interactions | Structured data |
| **Recent History** | Last 5-10 turns of dialogue (player input + response) | ~2000 tokens |
| **Active Threads** | Current story threads, unresolved consequences | Structured summary |
| **WorldSeed** | Original world parameters (tone, tech level, etc.) | Structured data |
| **Chapter Context** | Current chapter theme, arc position | Brief summary |

**FR-2.2** — The context assembly is **not raw turn history**. It is a structured
summary maintained by the system. Raw turn history is retained for reference but
compressed for generation context.

**FR-2.3** — The system MUST detect and prevent coherence violations before they
reach the player:
- Contradicting established facts (NPC who died appearing alive)
- Temporal inconsistencies (time going backward)
- Spatial impossibilities (player in two locations)
- Trait violations (character acting against established personality without cause)

**FR-2.4** — When a potential coherence violation is detected, the system MUST
regenerate the response, not post-hoc correct it. The player should never see
a retracted or amended response.

**FR-2.5** — Long-term memory (events from 50+ turns ago) is maintained through
structured world state (S04) and character state (S06), not through expanding
context windows. The narrative engine queries state, not raw history.

### FR-3: Context Management

**FR-3.1** — Context assembly follows a **priority-based packing** strategy. When
the total context exceeds the model's effective window, layers are compressed in
this order (lowest priority compressed first):

1. Distant turn history (summarized → omitted)
2. Inactive NPC states (omitted if not in scene)
3. Dormant story threads (summarized)
4. Active scene details (preserved in full)
5. Character state (preserved in full)
6. WorldSeed (always included, never compressed)

**FR-3.2** — The system MUST maintain a **running story summary** that is updated
after every chapter boundary. This summary captures key events, character
development, and world changes. It replaces raw history for distant events.

**FR-3.3** — Context assembly MUST be deterministic given the same game state. Two
identical calls with identical state MUST produce identical context (though the
generation itself may vary due to model sampling).

### FR-4: Narrative Quality

**FR-4.1** — Response prose MUST meet these quality criteria:

| Criterion | Requirement |
|-----------|-------------|
| **Sensory detail** | At least one sensory detail (sight, sound, smell, touch, taste) per response |
| **Variety** | No repeated sentence structures within a response |
| **Show don't tell** | Emotions shown through action/description, not stated ("she seemed angry" → "she slammed the cup down, coffee sloshing") |
| **Active voice** | Predominant active voice; passive only for deliberate effect |
| **Specificity** | Specific nouns and verbs over generic ones ("oak" not "tree," "sprinted" not "moved quickly") |

**FR-4.2** — Response length MUST be adaptive:

| Turn Type | Target Length | Justification |
|-----------|--------------|---------------|
| Action (combat, chase) | 80-150 words | Fast, punchy, kinetic |
| Dialogue (NPC conversation) | 100-250 words | Room for NPC voice and player reaction |
| Exploration (new area) | 150-300 words | Rich description, environmental storytelling |
| Introspection | 80-200 words | Internal, intimate, reflective |
| Chapter transition | 200-400 words | Ceremonial, summary, anticipatory |
| Climactic moment | 200-500 words | Everything converges; this is the payoff |

**FR-4.3** — The engine MUST avoid these anti-patterns:
- Starting every response with the player's action restated ("You walk to the door.
  Walking to the door, you notice...")
- Listing items mechanically ("You see: a table, a chair, a candle, a book")
- Over-describing static scenes (the third time the player is in a room, don't
  re-describe the furniture)
- Purple prose without substance (all style, no information)
- Ending every response with a question to the player ("What do you do?")

**FR-4.4** — The engine SHOULD employ narrative techniques:
- **Callbacks**: Reference earlier events naturally ("The smell of smoke reminds you
  of the warehouse — and of the choice you made there.")
- **Foreshadowing**: Plant details that become relevant later.
- **Subtext**: Not everything is on the surface. NPCs have hidden agendas that
  manifest subtly.
- **Running motifs**: Recurring images or phrases that build thematic resonance.

### FR-5: Pacing

**FR-5.1** — The engine MUST maintain a **tension model** that tracks the current
narrative energy level:

| Level | Description | Example |
|-------|-------------|---------|
| 1 — Calm | Rest, exploration, reflection | Walking through a peaceful village |
| 2 — Curious | Discovery, mystery, mild tension | Finding a strange symbol on a wall |
| 3 — Alert | Active problem-solving, social pressure | Negotiating with a hostile merchant |
| 4 — Intense | Combat, chase, confrontation | Fighting off bandits in a narrow alley |
| 5 — Climactic | Story-defining moments | The final confrontation with the antagonist |

**FR-5.2** — The engine MUST NOT sustain level 4-5 tension for more than 3-5
consecutive turns without a release. After high tension, the narrative should offer
a breath — a quiet moment, a reflection, a change of scene.

**FR-5.3** — The engine MUST NOT languish at level 1 for more than 5-8 consecutive
turns. If the player is exploring peacefully for too long, the world should
introduce a gentle escalation — a sound, a stranger, a discovery.

**FR-5.4** — Chapter transitions SHOULD follow a tension arc: rise from 1-2, through
3-4, to a chapter climax at 4-5, then resolve back to 1-2 before the next chapter
begins.

**FR-5.5** — The pacing system is a *guide*, not a straitjacket. Player actions that
dramatically shift tension (attacking someone during a calm scene) override the
pacing model immediately.

### FR-6: Genre Flexibility

**FR-6.1** — The engine MUST adapt its voice to the world's genre as defined by the
WorldSeed. The same functional scene ("player enters a building") reads differently
across genres:

- **Fantasy**: *"The tavern door creaks open on ancient hinges, spilling firelight
  and the smell of roasted game into the frost-sharp night."*
- **Sci-fi**: *"The airlock cycles with a hiss. Beyond it, the station bar pulses
  with holographic signage and the synthetic sweetness of recycled air."*
- **Mystery**: *"The office door is unlocked. Inside, everything is exactly as you'd
  expect — which is exactly what makes it wrong."*
- **Horror**: *"The door opens before you touch it."*

**FR-6.2** — Genre influences:
- Vocabulary and metaphor
- Sentence rhythm (short/staccato for horror/action, flowing for fantasy/romance)
- What details are emphasized (tech in sci-fi, atmosphere in horror, social cues
  in drama)
- NPC speech patterns (archaic for fantasy, clinical for sci-fi)

**FR-6.3** — Genre MUST remain consistent within a playthrough. Genre is set by the
WorldSeed and does not change mid-story.

### FR-7: Streaming

**FR-7.1** — All narrative responses are delivered via **Server-Sent Events (SSE)**.
The client receives tokens as they are generated.

**FR-7.2** — The SSE stream MUST include:
- Token data (the text being generated)
- A completion signal when generation finishes
- Error signals if generation fails

**FR-7.3** — The stream MUST be interruptible by the client (e.g., player navigates
away). Server-side generation continues to completion for state-update purposes but
the stream is closed.

**FR-7.4** — Streaming MUST feel smooth. Token delivery rate should be consistent
(no long pauses mid-sentence followed by bursts). If the model produces tokens
faster than reading speed, the client MAY buffer and smooth delivery.

**FR-7.5** — Markdown formatting in streamed text is NOT supported in v1. Narrative
is plain text with paragraph breaks. (Bold, italic, etc. are future considerations.)

### FR-8: Error Recovery

**FR-8.1** — If narrative generation fails (model error, timeout, malformed output),
the system MUST:
1. Retry once with the same context.
2. If retry fails, retry with a simplified context (recent turns only).
3. If that fails, deliver a graceful fallback: a brief in-world pause that
   acknowledges the moment without breaking immersion.
   Example: *"The world seems to hold its breath for a moment — as if deciding
   what comes next. And then..."* + prompt for player to try a different action.

**FR-8.2** — The player MUST NOT see raw error messages, stack traces, or "the AI
failed" notices. All failure states are handled in-world.

**FR-8.3** — If the generated narrative contains content that fails safety validation
(see S-Safety), the system regenerates with adjusted parameters. The player never
sees the unsafe content.

**FR-8.4** — If the model produces incoherent or off-topic output (hallucination,
genre break, character break), the system SHOULD detect this through coherence
checking (FR-2.3) and regenerate. Detection heuristics are implementation-level
but the *behavior* is: the player never reads incoherent output.

**FR-8.5** — Failed generation attempts MUST be logged for quality monitoring. Logs
include: input context (anonymized), failure reason, retry count, final outcome.

---

## Non-Functional Requirements

- **NFR-3.1** — First token MUST stream within 2 seconds of pipeline invocation (p95).
- **NFR-3.2** — Full response MUST complete within 15 seconds for standard turns (p95).
  Climactic/chapter transitions may take up to 25 seconds.
- **NFR-3.3** — Generation failure rate MUST be below 1% of turns (requiring fallback).
- **NFR-3.4** — Coherence violation rate MUST be below 0.5% of turns (requiring
  regeneration).
- **NFR-3.5** — The engine MUST support at least 3 simultaneous generation calls
  (different players) without degradation.
- **NFR-3.6** — Token streaming rate SHOULD be 15-30 tokens per second for readable
  pacing.
- **NFR-3.7** — Context assembly MUST complete within 500ms.
- **NFR-3.8** — The running story summary MUST NOT exceed 2000 tokens regardless of
  story length.

---

## User Journeys

### Journey 1: A Turn with Rich Description

1. Player is in a new location (first visit). Types: "I look around."
2. Context assembly gathers: location details from world model, current time/weather,
   active NPCs in location, player's emotional state, WorldSeed tone.
3. Engine generates a 200-word response with rich sensory detail, environmental
   storytelling, and 2-3 hooks for further exploration.
4. Player reads and discovers a detail that interests them.
5. The response took 4 seconds to stream. It felt natural, not rushed.

### Journey 2: A Turn with Tight Action

1. Player is in combat. Types: "I dodge behind the pillar and throw my knife."
2. Context assembly includes: combat state, enemy positions, player abilities,
   environmental objects.
3. Engine generates a 100-word response — punchy, kinetic, no wasted words. The
   outcome is uncertain — the knife throw is effective but the enemy adapts.
4. Player feels the urgency. The short response creates pace.

### Journey 3: Coherence Across Time

1. Turn 5: Player gives their last health potion to a wounded NPC named Sera.
2. Turn 47: Player is injured and asks Sera for help.
3. Sera produces the health potion — "the one you gave me, weeks ago. I've been
   saving it. Didn't feel right to use something given with such kindness."
4. The player feels the world remembers. This works because the character state (S06)
   tracks the gift, not because the engine remembers raw turn 5.

### Journey 4: Genre Adaptation

1. Two different players complete Genesis. Player A's world is gothic horror. Player
   B's world is lighthearted steampunk.
2. Both players type: "I enter the building."
3. Player A reads: *"The door yields with reluctant surrender. Inside, the air is
   thick and sweetish, like fruit left too long in the sun. Something moves in the
   corner. Something that isn't the shadows."*
4. Player B reads: *"The door pops open with a cheerful ding — some clever mechanism
   involving a brass bell and what appears to be a very small catapult. Inside,
   gears click and steam hisses from no fewer than seven different contraptions,
   none of which seem to serve an obvious purpose."*

---

## Edge Cases

- **EC-3.1**: Player input is in a different language. System responds in the language
  the game was started in (English for v1). Does not attempt translation.

- **EC-3.2**: Player input contains explicit or harmful content. System does not
  echo or amplify the content. Responds with an in-world redirect.

- **EC-3.3**: Model produces a response that is too short (<20 words for a standard
  turn). System appends additional generation or regenerates.

- **EC-3.4**: Model produces a response that is too long (>500 words for a standard
  turn). System truncates at a natural sentence boundary. Remaining content may
  inform world state but is not delivered.

- **EC-3.5**: Player references something from very early in the story (turn 3 of a
  100-turn game). System checks structured state first. If the reference is to a
  tracked entity, it responds accurately. If it's an untracked incidental detail,
  it responds vaguely but plausibly.

- **EC-3.6**: Two consecutive turns generate nearly identical responses (AI
  repetition). System detects similarity and regenerates the second response.

- **EC-3.7**: The player's WorldSeed produces a genre that's difficult to distinguish
  (e.g., "tone: neutral, tech_level: moderate"). System defaults to a balanced,
  grounded realistic-fiction voice.

- **EC-3.8**: Context window is nearly full due to a complex game state. System
  aggressively compresses lowest-priority context layers but ALWAYS retains:
  active scene, character state, WorldSeed.

---

## Acceptance Criteria

- **AC-3.1**: Given a standard gameplay turn, when the engine generates a response,
  then the response contains at least one sensory detail and no repeated sentence
  structures.

- **AC-3.2**: Given a player revisits a location they've been to before, when the
  engine generates a response, then the description is shorter and references
  what changed (not a copy of the first description).

- **AC-3.3**: Given 5 consecutive high-tension turns (level 4-5), when the 6th turn
  occurs, then the engine introduces a pacing shift (tension reduction or release).

- **AC-3.4**: Given a fantasy WorldSeed, when the engine generates narrative, then
  vocabulary, metaphor, and sentence rhythm are appropriate to fantasy genre.

- **AC-3.5**: Given the narrative generation model fails, when the system detects the
  failure, then it retries and if all retries fail, delivers a graceful in-world
  fallback (no error messages visible to the player).

- **AC-3.6**: Given a running game at turn 100, when the context assembly runs, then
  it completes within 500ms and the total context size does not exceed the model's
  effective window.

- **AC-3.7**: Given a coherence violation is detected (e.g., dead NPC appears alive),
  when the engine processes the response, then it regenerates before delivering to
  the player.

- **AC-3.8**: Given the player types an exploration input in a new location, when the
  engine responds, then the response is 150-300 words with environmental detail and
  at least two hooks for further interaction.

- **AC-3.9**: Given streaming is active, when tokens are delivered, then the delivery
  rate is consistent (no pauses >2 seconds mid-sentence).

- **AC-3.10**: Given the same game state and context, when context assembly runs twice,
  then both assemblies produce identical context payloads.

---

## Dependencies

| Spec | Relationship |
|------|-------------|
| **S01 — Gameplay Loop** | The engine is invoked for every turn in the gameplay loop. |
| **S02 — Genesis** | Genesis uses the engine for all creation narrative. |
| **S04 — World Model** | The engine reads world state for context assembly. |
| **S05 — Choice & Consequence** | Active consequence chains inform narrative generation. |
| **S06 — Character System** | Character state shapes narrator voice and response content. |
| **S13 — Storage Schema** | Turn history and summaries are persisted. |

---

## Open Questions

- **OQ-3.1**: Should the narrator ever have a "personality" — a distinct character
  with quirks — or should it be a transparent window into the world? Tradeoff:
  personality is memorable but risks annoying players who disagree with the voice.

- **OQ-3.2**: How do we measure narrative quality programmatically? Human eval is
  gold standard but doesn't scale. Are there proxy metrics (lexical diversity,
  sensory word count, repetition detection)?

- **OQ-3.3**: Should the engine support multiple models (e.g., use a larger model
  for climactic moments and a smaller/faster one for routine turns)? Pro: quality
  where it matters. Con: voice inconsistency risk.

- **OQ-3.4**: How aggressively should the running summary compress? Too much and
  callbacks feel shallow. Too little and the context window fills.

- **OQ-3.5**: Should the engine support player-adjustable verbosity? ("I want shorter
  responses" / "I want more detail.") This conflicts with adaptive length (FR-4.2)
  but respects player preference.

- **OQ-3.6**: What's the right balance between "show don't tell" and accessibility?
  Some players may miss subtext and need more explicit narrative communication.

---

## Out of Scope (v1)

- Multiple narrator voices per story (e.g., different narrator for flashbacks)
- Player-written narrative (collaborative storytelling)
- Image or audio generation alongside text
- Markdown, rich text, or formatted output (plain text + paragraph breaks only)
- Non-English narrative generation
- Player-configurable narrator personality
- Simultaneous multi-stream narrative (e.g., split-screen text for parallel events)
