# S06 — Character System

> **Status**: 📝 Draft
> **Release Baseline**: 🔒 v1 Closed
> **Implementation Fit**: ⚠️ Partial
> **Level**: 1 — Core Game Experience
> **Dependencies**: S00
> **Last Updated**: 2025-07-24

---

## Purpose

Characters are why people care about stories. Not worlds, not plot points — people.
A player who is invested in their character, who feels attached to their companions
and curious about their antagonists, will keep playing long after the novelty of the
world has faded.

This spec defines how characters exist in TTA: the player character who is the
player's window into the world, the NPCs who populate it with purpose and agency,
and the relationship web that makes interactions feel personal. The system must
produce characters who feel like *people*, not furniture.

The old TTA had PCs and NPCs with relationship tracking. We keep that core but
push harder on NPC autonomy, character development through play, and relationships
that are earned through behavior rather than selected from menus.

---

## User Stories

### Player Character

- **US-6.1**: As a player, I want my character to feel like *mine* — shaped by my
  choices, not by a template — so that I feel represented in the story.

- **US-6.2**: As a player, I want to see my character grow through the story — not
  through grinding — so that development feels earned and narratively meaningful.

- **US-6.3**: As a player, I want my character's personality to be reflected in how
  the world responds to me — NPCs treat me differently based on who I've shown
  myself to be.

- **US-6.4**: As a player, I want to be able to act against my established character
  traits — surprise myself — and have the world notice and react.

### NPCs

- **US-6.5**: As a player, I want NPCs to feel like they have lives and opinions
  beyond me — not like quest-dispensing vending machines.

- **US-6.6**: As a player, I want to be surprised by an NPC — they do something
  unexpected, reveal a hidden side, or make a choice that changes my plans.

- **US-6.7**: As a player, I want NPCs to remember me. If I was kind to someone,
  they should be warm when I return. If I wronged someone, they should be cold —
  or worse.

- **US-6.8**: As a player, I want NPC dialogue to feel distinct — each character
  should sound like themselves, not like generic "NPC talk."

### Relationships

- **US-6.9**: As a player, I want relationships with NPCs to develop over time —
  from stranger to ally (or enemy) — not flip instantly.

- **US-6.10**: As a player, I want to *earn* an NPC's trust through consistent
  behavior, not through a single "correct" dialogue option.

- **US-6.11**: As a player, I want the story to acknowledge my relationships —
  allies who help in crisis, enemies who hinder, and the complex ones in between.

---

## Functional Requirements

### FR-1: Player Character (PC) Definition

**FR-1.1** — The player character is defined by these components:

| Component | Description | Source |
|-----------|-------------|--------|
| **Name** | Chosen by the player during Genesis | Player input |
| **Traits** | 2-5 personality/behavioral descriptors | Inferred from Genesis + play |
| **Background** | 1-2 sentence origin story | Generated during Genesis |
| **Capabilities** | What the character can do | Inferred from demonstrated behavior |
| **Reputation** | How the world perceives the character | Accumulated from actions |
| **Inventory** | Items the character carries | Tracked through play |
| **Conditions** | Active states (injured, cursed, inspired) | Applied/removed during play |
| **Emotional state** | Current emotional register | Inferred from recent turns |

**FR-1.2** — PC traits are descriptive, not numerical. Examples:
- "Cautious" (not "Dexterity: 14")
- "Eloquent" (not "Charisma: 18")
- "Haunted by loss" (not "Backstory Flag: orphan")

**FR-1.3** — Traits influence the narrative in soft ways:
- A "cautious" character gets environmental details about threats and exits.
- An "impulsive" character gets descriptions that emphasize momentum and energy.
- A "scholarly" character notices inscriptions, mechanisms, and patterns.

**FR-1.4** — Traits are NOT restrictions. A "cautious" player can still do reckless
things. The system notes the departure from pattern:
*"This isn't like you — charging in without a plan. But something about this
moment demands it."*

### FR-2: PC Development

**FR-2.1** — Characters develop through **demonstrated behavior**, not through XP
or point allocation. Development types:

| Development Type | How It Works | Example |
|-----------------|-------------|---------|
| **Trait evolution** | Repeated behavior reinforces or shifts traits | Acting bravely shifts "cautious" toward "bold" |
| **Capability growth** | Successful use of skills improves them | Picking many locks → "skilled lockpick" |
| **Reputation change** | Actions affect how the world sees the PC | Helping the poor → "folk hero" reputation |
| **Emotional arc** | Character's emotional state evolves with story | Starting hopeful → hardened by betrayal → finding hope again |

**FR-2.2** — Trait evolution is gradual, not sudden. A trait shifts after 5-10
consistent actions, not one. The narrative marks the shift:
*"There was a time when you would have hesitated. When you would have weighed
every option. But those days are behind you now. You act on instinct, and the
instinct is right."*

**FR-2.3** — The player MUST be able to see their character's current traits and
reputation via `/character` command. The response is narrative, not a stat block:
*"You are Kael — quick-witted, stubborn, and known in Thornhaven as someone who
keeps their word. You carry a chipped blade and a letter you've never opened.
Lately, you've been quieter than usual."*

**FR-2.4** — Capabilities are **emergent, not selected**. If a player repeatedly
talks their way out of trouble, they develop a social capability. If they fight,
they develop combat capability. The system tracks behavior patterns and narrates
growing skill.

**FR-2.5** — Capabilities influence difficulty — not through dice rolls, but through
narrative framing. A character skilled in persuasion finds persuasion attempts
described more favorably. An unskilled character faces more resistance. But neither
outcome is predetermined — player creativity can overcome capability gaps.

**FR-2.6** — Character development MUST be visible in the narrative. The player
should *feel* their character becoming more capable/complex without being told
"you leveled up."

### FR-3: NPC Design

**FR-3.1** — Every NPC has these components:

| Component | Description |
|-----------|-------------|
| **Identity** | Name, appearance, occupation, mannerisms |
| **Personality** | 2-3 defining traits that shape behavior and speech |
| **Goals** | What the NPC wants (short-term and long-term) |
| **Knowledge** | What the NPC knows (and doesn't know) |
| **Disposition** | Current attitude toward the player (and other NPCs) |
| **History** | Past interactions with the player (full log) |
| **Schedule** | Daily routine (simplified) — see S04 |
| **Voice** | Distinct speech patterns, vocabulary, verbal tics |

**FR-3.2** — NPCs are classified by significance:

| Tier | Description | Example | Persistence |
|------|-------------|---------|-------------|
| **Key** | Central to the story | Mentor, antagonist, love interest | Full state, always tracked |
| **Supporting** | Recurring, important to regions/factions | Shop owner, faction leader | Full state, tracked when active |
| **Background** | Color and atmosphere | Passersby, crowd members | Minimal state, regenerated |

**FR-3.3** — Key NPCs (3-8 per story) are established during Genesis or early
gameplay. They have full internal lives: goals that conflict with the player's,
secrets, relationships with other NPCs, and arcs of their own.

**FR-3.4** — Supporting NPCs (10-20 per story) have consistent personalities and
basic goals but less narrative depth. They remember the player and react to history.

**FR-3.5** — Background NPCs are generated as needed and have no persistent state.
They provide atmosphere and incidental interaction. If a player develops interest
in a background NPC (repeated interaction), the system MAY promote them to
Supporting tier.

**FR-3.6** — NPC voice MUST be distinct. Examples:
- A nervous scholar speaks in run-on sentences with frequent self-corrections.
- A grizzled captain uses short sentences and nautical metaphor.
- A street urchin uses slang, avoids direct answers, and speaks in questions.

**FR-3.7** — The system MUST maintain voice consistency for each NPC across all
appearances. An NPC who speaks formally in turn 5 doesn't become casual in turn 50
unless character development justifies the shift.

### FR-4: NPC Autonomy

**FR-4.1** — NPCs ACT independently between player turns. Their actions are resolved
during the world-state update phase (see S04 FR-3.6) and include:
- Moving according to their schedule
- Pursuing their goals (acquiring resources, building alliances, investigating)
- Reacting to world events (taking shelter in storms, responding to threats)
- Interacting with other NPCs off-screen

**FR-4.2** — NPC autonomy is **proportional to significance**:
- Key NPCs have full autonomy — they pursue goals, make plans, and can create
  plot complications without player involvement.
- Supporting NPCs have routine autonomy — they follow schedules and react to
  events but don't generate new plot threads.
- Background NPCs have zero autonomy — they exist only in the player's presence.

**FR-4.3** — NPC autonomous actions MUST be:
- Consistent with their personality and goals
- Plausible given their knowledge (they can't act on information they don't have)
- Discoverable by the player (the effects are visible, even if the cause isn't)
- Non-contradictory to established player experience

**FR-4.4** — Key NPCs can SURPRISE the player. An NPC who seemed allied might
betray them. An NPC who seemed hostile might offer help. These surprises MUST be
grounded in the NPC's established (if hidden) goals and personality.

**FR-4.5** — The system tracks NPC goals and evaluates goal progress each turn.
If an NPC's goal conflicts with the player's current trajectory, the collision
becomes a narrative event.

### FR-5: Relationships

**FR-5.1** — Every PC-NPC relationship is tracked with these dimensions:

| Dimension | Range | What It Means |
|-----------|-------|---------------|
| **Trust** | -100 to +100 | How much the NPC trusts the player |
| **Affinity** | -100 to +100 | How much the NPC likes the player |
| **Respect** | -100 to +100 | How much the NPC admires the player |
| **Fear** | 0 to +100 | How intimidated the NPC is by the player |
| **Familiarity** | 0 to +100 | How well the NPC knows the player |

**FR-5.2** — Relationship dimensions change through interaction:

| Action | Trust | Affinity | Respect | Fear |
|--------|-------|----------|---------|------|
| Keep a promise | +15 | +5 | +10 | — |
| Break a promise | -25 | -10 | -15 | — |
| Help voluntarily | +10 | +15 | +5 | — |
| Threaten | -15 | -20 | -5 | +20 |
| Show vulnerability | +10 | +10 | -5 | -10 |
| Demonstrate competence | +5 | — | +15 | +5 |

(Values are illustrative, not exact. Actual values depend on NPC personality and
context.)

**FR-5.3** — Relationship changes are **gradual, not instant**. A single kind act
doesn't turn an enemy into an ally. Relationship shifts are capped per interaction:
- Single interaction: max ±15 on any dimension
- Exception: dramatic events (saving someone's life, betrayal) can shift ±30

**FR-5.4** — Relationships have **thresholds** that trigger behavioral changes:

| Trust Level | NPC Behavior |
|-------------|-------------|
| < -50 | Hostile: may attack, refuse service, spread rumors |
| -50 to -10 | Cold: minimal cooperation, terse dialogue |
| -10 to +10 | Neutral: polite but guarded |
| +10 to +50 | Warm: helpful, shares information, initiates conversation |
| > +50 | Loyal: goes out of their way to help, shares secrets, takes risks |

**FR-5.5** — NPC-NPC relationships ALSO exist and affect the world:
- If the player befriends NPC A, and NPC A dislikes NPC B, NPC B becomes warier
  of the player.
- If two NPCs the player knows are in conflict, the player may be asked to choose
  sides.
- NPC social networks create realistic-feeling politics.

**FR-5.6** — Relationship state MUST survive across sessions. The NPC remembers the
full history of interactions.

**FR-5.7** — The player can view their relationship standing with known NPCs via
`/relationships` command. Presented narratively:
*"Sera trusts you deeply — you've earned it through months of honesty. Aldric
respects your skill but doesn't trust your motives. Captain Voss fears what
you're capable of."*

### FR-6: Dialogue System

**FR-6.1** — NPC dialogue is generated dynamically, not scripted. Each NPC response
is generated considering:
- NPC personality and voice
- NPC knowledge (what they know and don't know)
- Relationship state with the player
- Current emotional state of the NPC
- Context of the conversation (topic, location, time)
- NPC goals (are they trying to get something from the player?)

**FR-6.2** — NPC dialogue MUST feel distinct from narrator prose and from other NPCs:
- Narrator: Second person, present tense, literary/genre-appropriate
- NPC: First person (their perspective), distinct vocabulary, personality markers

**FR-6.3** — Conversations are **multi-turn**. A player can have an extended
conversation with an NPC over several gameplay turns. The system maintains
conversation context within the scene.

**FR-6.4** — NPCs respond to *how* the player talks, not just *what* they say:
- Aggressive language triggers defensive NPC responses
- Respectful language opens NPCs up
- Deception attempts are evaluated against NPC perceptiveness
- Humor is acknowledged if the NPC's personality supports it

**FR-6.5** — NPCs can **refuse to answer**, **lie**, or **deflect**. Not every NPC
is an information dispenser. An NPC with secrets will:
- Change the subject
- Give a partial truth
- Ask a question instead of answering
- Become nervous or hostile if pressed

**FR-6.6** — NPCs can **initiate conversation** with the player. If an NPC has
information to share, a goal to pursue, or a reaction to recent events, they may
approach the player in an appropriate scene.

**FR-6.7** — The system tracks key dialogue for narrative callback. If the player
promised an NPC something in conversation, that promise is tracked as a
consequence chain (S05).

### FR-7: Companions

**FR-7.1** — NPCs MAY join the player as **companions** — persistent allies who
travel with the player and participate in scenes.

**FR-7.2** — Companion joining requires:
- Sufficient relationship standing (Trust > +30, Affinity > +20)
- Narrative justification (shared goal, mutual need)
- NPC willingness (autonomous decision based on their goals)

**FR-7.3** — Companions:
- Are present in scenes and referenced in narrative
- Offer commentary and reactions (interjections during exploration, warnings)
- Can act independently in some situations (fighting, scouting)
- Have their own inventory and capabilities
- Continue to develop as characters (their traits evolve too)

**FR-7.4** — Companions can **leave** if:
- Relationship deteriorates (Trust drops below -10)
- Their personal goal is achieved or abandoned
- A narrative event causes a rift
- The player dismisses them

**FR-7.5** — Maximum companions at once: **2** (v1). More would dilute individual
NPC characterization and complicate narrative generation.

**FR-7.6** — Companions remember their time with the player. A former companion
who leaves and is encountered later reacts based on their shared history.

### FR-8: Character Persistence

**FR-8.1** — The following character state MUST persist across sessions:

**Player Character:**
- Name, traits, background
- Capabilities and development history
- Inventory and conditions
- Reputation scores (per faction, per region)
- Emotional state

**NPCs (Key and Supporting):**
- All components listed in FR-3.1
- Full interaction history with the player
- Current position and schedule state
- Relationship dimensions
- Goal progress

**FR-8.2** — Character state is saved as part of the auto-save system (S01 FR-5).

**FR-8.3** — On resume, the system reconstructs character context: who the player
is, who they're with, and what their relationships are. This feeds into the
recap system (S01 FR-5.4).

**FR-8.4** — Character death (NPCs) is permanent. A dead NPC is marked as dead in
the world state and does not return. Other NPCs may reference the death. The world
adjusts: a dead shopkeeper's shop is closed or taken over.

**FR-8.5** — Player character "death" is handled by S01 FR-6.1 (narrative
recovery). The character persists through apparent death.

---

## Non-Functional Requirements

- **NFR-6.1** — NPC dialogue generation MUST begin streaming within 2 seconds.
- **NFR-6.2** — Relationship state updates MUST complete within 200ms per
  interaction.
- **NFR-6.3** — NPC voice consistency MUST be maintained across all appearances
  (measured by human evaluation, sampled quarterly).
- **NFR-6.4** — The system MUST support at least 50 named NPCs per world
  (Key + Supporting) without state management degradation.
- **NFR-6.5** — Character state queries (who is near the player, relationship
  status, NPC knowledge) MUST complete within 200ms.
- **NFR-6.6** — PC trait update evaluation (checking if behavior justifies a
  trait shift) MUST NOT exceed 300ms per turn.

---

## User Journeys

### Journey 1: Building Trust

1. Turn 5: Player meets Sera, a wary merchant. Disposition: Neutral. Trust: 0.
2. Turn 12: Player returns stolen goods to Sera. Trust: +15. Affinity: +10. Sera
   says: "Most people wouldn't have bothered. Thank you."
3. Turn 25: Player asks Sera about a dangerous topic. Because Trust is moderate,
   Sera hesitates but shares: "I shouldn't tell you this, but... I think you've
   earned it."
4. Turn 40: Sera is in trouble. She comes to the player for help — because Trust
   is high enough that she believes they'll help. "I didn't know who else to ask."
5. Turn 55: Sera offers to join as a companion. "Wherever you're going — I'd
   rather go there than stay here alone."

### Journey 2: An NPC with Agency

1. Turn 10: Player meets Commander Voss, who is tracking a fugitive. Player offers
   to help.
2. Turn 20: Player and Voss part ways. Voss continues her hunt (off-screen NPC
   autonomy).
3. Turn 35: Player encounters the fugitive in a different town — before Voss.
   The player has a choice: capture them, help them escape, or stay out of it.
4. Turn 38: Regardless of the player's choice, Voss arrives. She's been tracking
   the fugitive independently. Her reaction depends on what the player did.
5. The player realizes: Voss has been living her own story. The world doesn't
   revolve around the player.

### Journey 3: Character Growth Through Action

1. Early game: Player's character starts with the trait "Cautious." They observe,
   plan, and avoid confrontation.
2. Mid-game: Circumstances force the player into action. They start making bolder
   choices — not because they chose "be bold" from a menu, but because the story
   demanded it.
3. Turn 60: After 15+ turns of increasingly bold behavior, the system shifts the
   trait: "Cautious" → "Determined." The narrative marks it:
   *"Somewhere along the road between Thornhaven and here, the person who hesitated
   at every doorway became the person who kicks them open. You're not sure when it
   happened. But looking at your hands — steady, ready — you know it did."*

### Journey 4: NPC Deception

1. Turn 10: Player meets Alistair, a charming noble. He's helpful, generous,
   well-spoken. Affinity grows quickly.
2. Turn 30: Subtle cues appear — Alistair asks probing questions, always steers
   conversation toward the player's quest. The player may or may not notice.
3. Turn 45: Alistair betrays the player. He's been working for the antagonist.
   The betrayal is shocking — but if the player replays the interactions, the
   signs were there. His questions were too specific. His generosity had a price.
4. The system seeded the betrayal from turn 10 — Alistair's hidden goal was
   always espionage. His personality (charming, calculated) supported the deception.
   His dialogue choices (probing, redirecting) were generated to fit.

---

## Edge Cases

- **EC-6.1**: Player tries to romance an NPC. System handles romantic subtext
  narratively if Affinity and Trust are very high, but does not generate explicit
  content. Romance is emotional, not physical, in v1.

- **EC-6.2**: Player is abusive toward an NPC (repeated insults, threats). NPC
  relationship deteriorates rapidly. Eventually the NPC refuses to interact:
  *"They turn away from you. Some bridges, once burned, stay burned."*

- **EC-6.3**: Player tries to have a conversation about a topic the NPC knows
  nothing about. NPC responds authentically: *"I don't know the first thing about
  that. You might try the scholar at the university."*

- **EC-6.4**: NPC with low Trust is asked to do something risky. NPC refuses or
  demands compensation: *"Why would I stick my neck out for you? What's in it
  for me?"*

- **EC-6.5**: Player has two companions who dislike each other. Inter-NPC tension
  surfaces in dialogue: bickering, passive-aggressive comments, competing for the
  player's attention. Eventually one may leave if the tension isn't addressed.

- **EC-6.6**: Player tries to give an NPC an item that makes no narrative sense
  (offering a sword to a baby). System handles gracefully: *"The child stares at
  the blade with wide, uncomprehending eyes. Perhaps not your best idea."*

- **EC-6.7**: A Key NPC dies. The story must continue. The system identifies which
  narrative functions the NPC served (quest-giver, information source, antagonist)
  and redistributes those functions to other NPCs or introduces a new one.

- **EC-6.8**: Player creates a character in Genesis that is very similar to a
  previous playthrough's character (same name, similar traits). System does not
  prevent this — each playthrough is independent. No "you already used that name."

- **EC-6.9**: Player's emotional state (inferred) and character's emotional state
  diverge. The character feels grief; the player seems amused. System follows
  the *character's* emotional arc in narrative, not the player's real-time mood.

---

## Acceptance Criteria

- **AC-6.1**: Given a player completes Genesis, when they view `/character`, then
  a narrative description of their character including name, 2-5 traits, and
  background is displayed.

- **AC-6.2**: Given a player acts contrary to their established traits 10+ times,
  when the system evaluates, then the relevant trait shifts and the narrative
  acknowledges the change.

- **AC-6.3**: Given a player interacts with an NPC, when they view `/relationships`,
  then the NPC appears with a narrative description of the relationship standing.

- **AC-6.4**: Given a player helps an NPC, when the relationship is evaluated, then
  the appropriate dimensions (Trust, Affinity, Respect) increase by context-
  appropriate amounts.

- **AC-6.5**: Given two NPC dialogue responses from different NPCs in the same scene,
  when compared, then the responses exhibit distinct vocabulary, sentence structure,
  and personality markers.

- **AC-6.6**: Given a Key NPC has a hidden goal, when the NPC interacts with the
  player, then the NPC's dialogue is subtly influenced by their goal (information
  seeking, agenda pushing) without explicitly revealing it.

- **AC-6.7**: Given a companion NPC travels with the player, when a new scene is
  described, then the companion is referenced in the narrative (commentary,
  reaction, or action).

- **AC-6.8**: Given a player returns to a game after a session break, when they
  interact with a previously-met NPC, then the NPC references shared history
  appropriately.

- **AC-6.9**: Given a player asks an NPC about a topic beyond the NPC's knowledge,
  when the NPC responds, then the response acknowledges the knowledge gap
  authentically (not a generic "I don't know").

- **AC-6.10**: Given a Key NPC dies during gameplay, when subsequent turns are
  processed, then other NPCs reference the death and the dead NPC's narrative
  functions are redistributed.

---

## Dependencies

| Spec | Relationship |
|------|-------------|
| **S01 — Gameplay Loop** | Character state is read/updated every turn. |
| **S02 — Genesis** | Genesis creates the initial PC and first NPCs. |
| **S03 — Narrative Engine** | The engine uses character state for voice, tone, and content. |
| **S04 — World Model** | NPCs exist as entities in the world model. NPC positions/schedules live there. |
| **S05 — Choice & Consequence** | Player actions toward NPCs are tracked as consequence chains. |
| **S13 — Storage Schema** | Character and relationship state must be persisted. |

---

## Open Questions

- **OQ-6.1**: How many traits should a PC have? Too few and the character is flat.
  Too many and they're unfocused. Current thinking: 2-3 during Genesis, up to 5
  through play.

- **OQ-6.2**: Should NPCs have visible "stats" (even narratively expressed) or
  should their capabilities be entirely emergent? If a player asks "is this NPC
  strong?", should they get a definitive answer or an impression?

- **OQ-6.3**: How do we prevent all NPCs from sounding like the same person with
  different accents? Voice distinction is critical and hard. Dedicated prompt
  engineering per NPC? Voice templates?

- **OQ-6.4**: Should companion NPCs ever disagree with the player's choices in
  a way that blocks progress? Or only in a way that adds flavor? Blocking feels
  authentic but frustrating.

- **OQ-6.5**: Should the player be able to play as a deliberately "evil" character?
  If yes, how does the NPC system handle a player who antagonizes everyone? The
  world should adapt, not punish.

- **OQ-6.6**: How do we handle NPC "memory" for very long games? After 200 turns,
  does an NPC still reference turn 3? Should their memory fade naturally?

- **OQ-6.7**: Should romantic relationships have explicit gameplay implications
  (NPC loyalty bonuses, narrative privileges) or should they be purely narrative?

---

## Out of Scope (v1)

- Player character customization (appearance, portrait)
- NPC visual representations (portraits, sprites)
- Character classes, skill trees, or traditional RPG stat blocks
- Party management UI (companion inventory, formation)
- NPC scheduling editor (player cannot change NPC routines)
- Character creation outside of Genesis (no standalone character builder)
- Cross-world character import ("bring my character to a new world")
- Pet/animal companions (only humanoid NPCs as companions in v1)
- NPC romance as a core mechanic (emotional subtext is in; explicit romance
  systems are out)
- Voice acting or audio for NPC dialogue

---

## v1 Closeout (Non-normative)

### What Shipped

| Item | Shipped | Verified | Evidence | Notes |
|------|---------|----------|----------|-------|
| /character displays WorldSeed-derived attributes (AC-6.1) | ✅ | ✅ | `test_s06_character_system.py` | PC traits from genesis visible |
| Relationship dimensions updated on interaction (AC-6.3, AC-6.4) | ✅ | ✅ | `test_s06_character_system.py`; `test_s06_ac_compliance.py::TestRelationshipUpdate` | Affinity/trust delta on help |
| Distinct NPC vocabulary markers in generation prompt (AC-6.5) | ✅ | ✅ | `test_s06_character_system.py::TestNPCSection` | `_build_npc_section` includes vocabulary |
| Hidden NPC goal influence in dialogue (AC-6.6) | ✅ | ✅ | `test_s06_character_system.py::TestHiddenGoalPrompt` | `goals_short` injected |
| Companion NPC presence in scene prompt (AC-6.7) | ✅ | ✅ | `test_s06_character_system.py::TestCompanionIdentification` | `_identify_companions` detects co-located companions |
| Session-break recognition on return (AC-6.8) | ✅ | ✅ | `test_s06_ac_compliance.py::TestSessionBreakGreeting` | Greeting flag set after break |
| Out-of-knowledge NPC deflection (AC-6.9) | ✅ | ✅ | `test_s06_ac_compliance.py::TestOutOfKnowledgeResponse` | NPC doesn't fabricate beyond knowledge scope |

### Deferred to v2

| Item | Reason | v2 Priority |
|------|--------|-------------|
| Trait evolution from repeated contrary actions (AC-6.2) | No trait-mutation subsystem in v1; traits are static post-genesis | High |
| NPC death state tracking (AC-6.10) | No death-event subsystem; NPCs remain in context after death | High |
| NPC memory of prior player interactions | No cross-session NPC memory store | High |
| Pet/animal companions | Humanoid NPCs only in v1 | Low |
| Romance mechanics | Emotional subtext in; explicit romance systems out | Low |

### Gaps Found

**NPC memory gap**: NPCs have personality and vocabulary markers injected per-turn from template data, but no persistent memory of what the player has said or done to them in prior sessions. Returning to a long-running game, an NPC will not remember a promise, debt, or grievance from session 1. This is the most player-visible character-system gap in v1.

**Trait evolution absent (AC-6.2)**: Player traits are seeded at genesis and remain static. The spec envisions trait drift after 10+ contrary actions. No counter or mutation mechanism exists. This manifests as players who consistently act against their stated traits receiving no narrative acknowledgement of the contradiction.

**NPC death (AC-6.10)**: If a Key NPC is marked dead in world state, the generate stage continues to include them in the NPC context section via `_build_npc_section`. There is no filter on death state before prompt injection. Dead NPCs may appear in generated narrative.

