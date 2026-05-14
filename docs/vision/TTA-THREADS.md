# TTA Threads Reference

**Status**: Companion to [TTA Unified Vision & Roadmap](./TTA-UNIFIED-VISION.md)
**Created**: 2026-05-13
**See also**: [Strategy & Planning](./TTA-STRATEGY.md)

---

## Specability

Phases follow the SDD pattern: early versions produce specable behaviors (testable
acceptance criteria), later versions are directional compass headings that will be
fully specced when the relevant version gate is reached.

- **v1–v2.1 phases**: Specable — each phase resolves to testable ACs.
- **v3 phases**: Mixed — most are specable, but emergent behaviors ("NPC society
  produces stories") resist full specification and need quality-evaluation fallback.
- **v4 phases**: Mostly directional — defines what we want, but depends on v3
  learnings and unproven technology. Treated as boundary stubs, like S18-S22.
- **v5 phases**: Boundary stubs only — compass heading, not a spec. Full specs
  written at the v4→v5 gate, informed by everything learned.

The SDD contract: specs are source of truth. Where a phase can't be specced yet,
it's marked as a boundary stub — direction locked, implementation deferred.
The actual spec for that phase gets written when the version is reached.

Detailed descriptions of each thread — how it matures across versions, key
architecture decisions, and how it connects to other threads.

## Simulation Depth
The world's fidelity — how alive, persistent, and reactive it feels.

| Phase | Version | What |
|-------|---------|------|
| Linear world | v1 | Static locations, basic NPCs, no off-screen activity |
| Persistent universe | v2.0 | Universe entities, diegetic time, NPC autonomy, consequence propagation, world memory |
| Quality-validated | v2.1 | Simulation quality measured by automated playtesters |
| Production-scale | v3 | Multiple concurrent players in persistent worlds, zero downtime |
| Multiverse depth | v4 | Multiple universes loaded concurrently, cross-universe events, resonance |
| Full depth | v5 | Player-authored world rules, emergent cultural simulation |

## Gameplay Loop
How the core interaction works — what the player does, what happens between
input and output, and how the experience matures.

| Phase | Version | What |
|-------|---------|------|
| Free-text turns | v1 | Player types free text. Linear 4-stage pipeline. SSE stream output. Three turn types emerge: **system** (commands, config, "save game"), **narrative** (receiving from the narrator, exposition), and **scene** (character taking action in response to context). Each has different data requirements — system turns need game state, narrative turns need world context, scene turns need character state + immediate situation. |
| Context-enriched turns | v2.0 | NPC memories, relationships, and consequence history enrich generation. Choice classification identifies what kind of action the player took. Turn type detection becomes explicit — the engine recognizes which of the three types a turn belongs to. |
| Structured turns | v2.1 | Choice buttons alongside free-text input. Turn quality metrics (coherence, tone) measured per-turn. Lore consistency checks before output. |
| Quest arcs | v3 | Multi-turn quests with narrative structure. Beat tracking (tension/release, scene pacing). Turn types expand: combat, dialogue, investigation. Player sees quest progress. |
| Decision-matrix turns | v4 | 4-factor weighted generation per turn (Narrative × World × Character × Randomness). Emotional feedback loops — NPCs react to emotional tone. NPCs initiate turns (they approach the player). |
| Multi-perspective turns | v5 | TLC Monk narrative voices offer different perspectives on the same turn. Concept-driven generation steers thematic direction. Players can switch narrator voice mid-session. |

The gameplay loop matures along three axes:

**Input**: Free text only (v1) → Free text + choice buttons (v2.1) → Structured commands + choices (v3) → Voice input (v4) → Multi-modal (v5)

**Processing**: Linear pipeline (v1) → Context-enriched (v2.0) → Quality-checked per turn (v2.1) → Beat-tracked scenes (v3) → Decision-matrix generation (v4) → Multi-perspective generation (v5)

**Output**: Streaming prose (v1) → Styled prose + status updates (v2.1) → Prose + character sheet changes + quest log (v3) → Prose + world map changes + NPC relationship shifts (v4) → Prose + multiple narrator voices + thematic summaries (v5)

## Game Systems
How rules, mechanics, abilities, and advancement work — and how the system
itself is negotiable. The game system is orthogonal to narrative: the same
world can be experienced through different mechanical lenses.

| Phase | Version | What |
|-------|---------|------|
| None | v1-v2.0 | No formal game system. Actions succeed or fail based on narrative logic. World-based realism only — Genesis defines what's possible. Magic exists if the world has magic; it doesn't if the world is realistic. No character stats, no advancement, no risk mechanics. |
| World-based | v2.1 | Genesis infers a basic system from the world it creates. Fantasy world → simple stats (strength, intelligence). Sci-fi world → tech aptitude. Basic ability checks. Advancement tracked as narrative milestones, not XP. Players can specify a preferred system during Genesis. |
| OSS baseline | v3 | First open-source system integrated (D&D 5e SRD as default fantasy baseline). Character sheets with full stats. Combat with initiative and actions. Spell lists and equipment tables. Players opt into system rules or stay narrative. System-agnostic fallback: if no system selected, world-based logic applies. |
| Multi-system | v4 | Multiple OSS systems available (5e, Fate, PbtA, OSR, custom). System selection at Genesis. System affects NPC behavior, economy, magic availability. Same universe can be saved and replayed under different systems — the narrative is constant, the mechanics are swappable. |
| Player-defined | v5 | Players define custom systems. Community-shared system templates. Mix-and-match: 5e combat + Fate social encounters. System as universe property — export a universe and its system travels with it. System discovery: the engine infers which system a player prefers from their playstyle. |

The key architecture decision: **game systems are plugins to the narrative engine.**
The pipeline generates narrative content. The game system resolves mechanical
outcomes. They share a contract (what action was attempted, what was at stake)
but remain independent. This means a universe exported by a 5e player can be
imported by a Fate player — same world, different rules.

Player agency over systems follows a progression:
- v1-v2.0: No choice. No system.
- v2.1: Genesis asks "what kind of world?" which implies a system. Player can override.
- v3: Explicit system selection during Genesis. "Play with 5e rules" or "Play narrative-only."
- v4: System menu. Try different systems in the same universe.
- v5: Build your own. Share it. The system IS content.

## Difficulty & Failure
How hard the game is, what happens when the player character fails or dies,
and how player intent shapes the experience. Priority order is system → theme
→ therapeutic → transcendental (crunchy to fluffy).

Some players never want their character to die. Others want DOOM. The system
must detect intent, respect explicit configuration, and fall back to what the
chosen game system says about death.

| Phase | Version | What |
|-------|---------|------|
| None | v1-v2.0 | No death mechanics. Actions succeed or fail narratively. No permanent consequences. |
| Narrative-only | v2.1 | Player death is a narrative event, not a mechanical one. Death = story beat with consequences (injury, capture, loss). Configurable: "no death ever" toggle. |
| Player-configured | v3 | Difficulty settings: narrative (death = story), forgiving (rare death, easy recovery), standard (system rules), hardcore (permadeath). Game system resolves death mechanics (5e: death saves, Fate: consequences). |
| System-defined | v4 | Each game system defines its own death/failure model. Player chooses system → inherits its death rules. Cross-universe death: character dies in one universe, lives in another. |
| Adaptive difficulty | v5 | Engine infers player's preferred challenge level from play patterns. Difficulty adjusts per-player. Transcendental layer: death as transformation, not ending. Character death opens new narrative paths. |

Death is handled across four concerns, in priority order:
1. **Systematic** (what does the game system say?) — 5e has death saves. Fate has consequences. Narrative-only has story beats.
2. **Thematic** (what does the Genesis/theme say?) — a dark fantasy world treats death differently than a heroic epic.
3. **Therapeutic** (how does death affect growth?) — death as narrative closure, not punishment. v5's transcendental layer.
4. **Transcendental** (the biggest picture) — death as transformation, rebirth, legacy.

## Progression & Achievements
How players are rewarded, recognized, and motivated — from simple milestone
tracking to community badges and player-defined goals.

| Phase | Version | What |
|-------|---------|------|
| None | v1-v2.0 | No progression tracking. No achievements. |
| Milestone tracking | v2.1 | Basic progression: turn count, locations visited, NPCs met. Narrative milestones tracked (completed first quest, discovered hidden area). |
| Achievements | v3 | Named achievements with unlock conditions. "First Light" (complete Genesis), "Worldwalker" (visit every region), "Silver Tongue" (resolve conflict through dialogue). Achievement display on player profile. |
| Community badges | v4 | Shared achievements across players. Rare achievements visible to community. Character passport carries achievements between universes. |
| Player-defined | v5 | Players create custom achievements. Guild/party achievements. Achievement-based narrative triggers. Badges become world artifacts. |

Progression is positive feedback — players should feel recognized for everything
from small actions ("talked to your first NPC") to epic accomplishments
("united the warring factions"). The system gets more celebratory over time.

## Economy & Trade
How resources, trade, and markets work — from static world props to dynamic
economic simulation. Drawn from Dukat's detailed economic model.

| Phase | Version | What |
|-------|---------|------|
| None | v1-v2.1 | Economy is narrative flavor only. Items have descriptions but no prices. Trade is hand-waved. |
| Static resources | v3 | Items have values. Factions have economicFocus and financialResources. Trade routes exist as static world data. Prices are fixed. |
| Dynamic trade | v4 | Supply/demand affects prices. Trade routes shift based on world events. Factions gain/lose wealth. NPCs have personal economies (wages, spending). |
| Full simulation | v5 | Resource extraction chains. Production pipelines. Market fluctuations. Player can engage in trade, build wealth, influence economies. Economic events cascade through faction relationships. |

Dukat's economic model (resource extraction → processing → manufacturing →
transport → market) maps naturally to v5's full simulation. Earlier versions
build the data model that v5's simulation runs on.

## NPC Society
How NPCs interact with each other — beyond their interactions with the player.

| Phase | Version | What |
|-------|---------|------|
| None | v1 | NPCs are static props. No off-screen activity. No NPC-to-NPC interaction. |
| Basic autonomy | v2.0 | NPCs have goals that progress off-screen. They move between locations. But they don't interact with each other — only with the world. |
| Faction dynamics | v2.1 | NPCs within factions have relationships. Faction alliances and rivalries shift based on events. NPCs react to faction-level changes. |
| Emergent stories | v3 | NPC-to-NPC interactions produce narrative events. Two NPCs with conflicting goals generate a conflict event. An NPC's personal history affects their behavior toward another NPC. The world generates stories without the player. |
| Cross-universe NPCs | v4 | NPCs can exist in multiple universes (different versions). Character passport applies to NPCs too. NPC fame/prestige carries between universes. |
| Player impact | v5 | Player actions ripple through NPC society visibly. An NPC the player helped becomes a faction leader. An NPC the player wronged builds a coalition against them. The world's history is shaped by both player and NPC actions. |

## Save/Load
How player progress is saved, loaded, shared, and managed.

| Phase | Version | What |
|-------|---------|------|
| Manual save | v1-v2.0 | Save to Postgres. Load from game list. Single save per game. |
| Auto-save + slots | v2.1 | Auto-save after every turn (configurable). Multiple save slots per game. Save metadata (turn count, location, timestamp). |
| Save sharing | v3 | Export saves as files. Import saves from other players. Save compatibility validation. Story export from save (PDF/ePub). |
| Cross-universe saves | v4 | Character passport includes save state. Load a character into a different universe. Save compatibility across universe versions. |
| Save editing | v5 | Players can edit saves (branch, rewind, fork). Save version history. Collaborative saves (multi-player game state). |

## Maps & Travel
How the world is navigated spatially — from text descriptions to interactive
maps with fog of war, travel mechanics, and hidden discoveries.

Drawn from Dukat's spatial hierarchy (continent → region → location → site),
travel system (Mode × Terrain × Period × Modifiers), and route mapping.

| Phase | Version | What |
|-------|---------|------|
| None | v1 | Locations exist as Neo4j nodes. No coordinates. No spatial relationships beyond narrative description. Travel is narrative hand-waving. |
| Spatial relations | v2.0 | Locations have spatial relationships (adjacent, contains, north-of). Basic travel time between connected locations. Sites exist within locations. |
| Routes + distances | v2.1 | Travel routes with distances and terrain types. Route-specific encounters and challenges. Text-based map output (ASCII or minimal rendering). Travel time = mode × terrain. |
| Interactive map | v3 | Graphical world map with fog of war — player sees only explored areas. Continent → region → location → site drill-down. Coordinates for all locations. Hidden areas and secret paths marked on map only when discovered. Travel simulation with resource consumption. |
| Cross-universe maps | v4 | Maps persist across universes. Annotate maps with player notes. Share maps with other players. Maps reveal universe compatibility (common regions). |
| Dynamic discovery | v5 | Maps update with world events (a new ruin appears, a forest burns). Procedural generation of unexplored areas. Hidden lore embedded in map geography. Super-secrets — locations invisible until specific conditions met. |

Dukat's "influence auras" (cultural, religious, military influence emanating from
locations) and "super-secrets" concept (developer-only hidden lore gradually
revealed to players) feed into v5's dynamic discovery.

## Image Generation
AI-generated visuals for scenes, characters, locations, and items — from
optional illustrations to a consistent visual layer across the game.

| Phase | Version | What |
|-------|---------|------|
| None | v1-v2.0 | Text only. No image generation. |
| Basic portraits | v2.1 | Character portraits and location illustrations generated from narrative descriptions. Manual trigger ("show me this character"). Prompt crafted from world state. |
| Scene illustrations | v3 | Auto-generated illustrations during key narrative moments. Character portraits in character sheet. Location images in world map view. Item illustrations. |
| Style consistency | v4 | All images in a universe share a consistent art style (defined at Genesis). NPC portraits maintain visual identity across appearances. Image prompts tuned for coherence. |
| Player-customizable | v5 | Players choose art styles. Generated images become world artifacts (a discovered painting, a wanted poster). Image galleries per universe. Community-shared style presets. |

Image generation connects to Prompt Engineering: the craft of constructing image
prompts from world state is the same meta-prompting capability that generates
text prompts. A character description becomes both a narrative passage and an
image prompt — same source data, different output modality.

## Cross-Cutting Concerns

Some capabilities don't fit neatly into a single thread but must mature across
all of them. These are **design constraints** applied to every thread, not
features scheduled in a specific version.

**Accessibility**: Screen reader support from v2.1 (semantic HTML). Keyboard
navigation from v3. Voice input from v4. Full WCAG compliance by v5.

**Localization**: English-only through v4. i18n infrastructure in v4 (string
extraction, translation framework). Community translations in v5.

**Error handling**: S23 covers v1 (retries, circuit breakers, turn atomicity).
As complexity grows, error handling must expand: NPC autonomy failures (v2.0),
playtester session isolation (v2.1), multi-player conflict resolution (v3),
cross-universe state inconsistency (v4), therapeutic safety failures (v5).

**Testing**: Unit + integration + BDD (v1). Automated playtesting (v2.1).
Load testing + chaos engineering (v3). Cross-universe integration tests (v4).
Therapeutic safety validation (v5).

**Observability**: Structured logging + OTel + Langfuse (v1). Playtester
session analytics (v2.1). Player experience dashboards (v3). Distributed
tracing across self-host instances (v4). P2P network health monitoring (v5).

## Context Engineering
How each agent's context window is constructed — what they see, how it's
formatted, how stale information is pruned, and how agents share information.

Every agent in TTA (turn pipeline, NPC autonomy, playtesters, TLC Monks) is
an LLM call with a context window. What goes in that window determines what
the agent can do. As the number and diversity of agents grows, context
engineering becomes a first-class concern.

| Phase | Version | What |
|-------|---------|------|
| Fixed window | v1 | Single agent (turn pipeline). Context = world state snapshot + recent turn history + character sheet. Fixed structure, no variation. |
| Per-agent templates | v2.0 | NPC autonomy agents join. Each agent type has its own context template. Playtester agents (v2.1) get game state + evaluation criteria. Context is assembled from templates, not custom per call. |
| Agent comms | v2.1 | Agents share information. NPC gossip propagates through the world graph — one NPC's context includes what another NPC "knows." Playtester agents share findings between runs. |
| Dynamic context | v3 | Agents request additional context on demand. "Tell me more about this NPC." Context compression for long histories — summarize rather than truncate. Context budgets per agent type (playtester gets more tokens than NPC autonomy). |
| Cross-agent context | v4 | Shared context bus. TLC Monks see what the narrator sees. NPCs share a world-memory pool. Context versioning — agents can request "world state as of turn 47." |
| Self-optimizing | v5 | Langfuse tracks which context produces best outcomes per agent type. Context templates auto-tuned based on evaluation scores. Agents learn what information they actually need vs what's noise. |

Context engineering connects to Prompt Engineering: prompt templates define
*how* the context is used; context engineering defines *what* goes into it.

## Self-Improving Narrative (Langfuse Feedback Loop)

The Prompt Engineering thread describes self-improving prompts at v5. This is
the concrete mechanism using Langfuse's evaluation infrastructure:

```
Generation → Langfuse trace (prompt version + output)
    → Evaluation (automated playtester scores: coherence, engagement, pacing, tone)
    → Score stored in Langfuse alongside prompt version
    → Langfuse shows: which prompt variants produce highest-scoring output?
    → System promotes better-performing prompts (or suggests promotions)
    → Over time, narrative quality improves without manual prompt engineering
```

This isn't just "prompts get better." It's a **closed-loop improvement system**:

- **v2.1**: Langfuse prompt versioning enables A/B comparison. Quality metrics
  are tied to prompt versions. Manual analysis: "does variant B score higher?"
- **v3**: Automated scoring pipeline. Playtester agents score every generation.
  Langfuse dashboards show prompt performance over time. Human reviews flagged
  regressions.
- **v4**: Automated promotion. Prompt variants that consistently outperform
  baseline are automatically promoted to production. Safety gate: human
  approval required for dramatic changes.
- **v5**: Full self-improvement. The system proposes prompt variants, tests
  them via playtester agents, measures scores, and promotes winners. The
  narrative engine gets better the more it's played.

This turns Langfuse from an observability tool into an **editor** — a system
that watches, measures, and improves narrative quality continuously.

## Multiplayer
How players connect — from solo to shared worlds.

| Phase | Version | What |
|-------|---------|------|
| Solo | v1-v2.1 | One player, one universe. No multiplayer. |
| Invite-only private | v3 | Player hosts their universe, friends join via invite link. Self-hosted instance. |
| P2P public sharing | v4 | Players publish universes, characters, stories. Discovery via P2P tracker. Character passport (take your character to other universes). |
| Central Nexus | v5 | A hub universe that connects all universes. Characters hop between servers. The P2P tracker becomes a universe itself. |

Multiplayer is not one feature. It is three distinct architectural phases:
1. **Invite** (v3): Your universe, your friends. Self-hosted, private. Simplest model — you run the instance, they connect. No discovery, no character portability.
2. **Share** (v4): Publish to a P2P directory. Others can join public universes. Character passport — take your character between compatible universes. Cross-universe travel protocol.
3. **Nexus** (v5): A central universe that IS the directory. Characters exist in the Nexus and travel outward. The tracker becomes a universe — with its own locations, NPCs, and narrative.

## Worlds & Content
How rich and diverse the game worlds are — the output of Genesis + ongoing generation.

| Phase | Version | What |
|-------|---------|------|
| Template worlds | v1 | Genesis-lite produces basic worlds: a few locations, NPCs, items |
| Deep worlds | v2.0 | Genesis v2 produces richer starting worlds. Detailed locations, NPC histories, faction relationships |
| Procedural depth | v2.1 | Rich location descriptions, dynamic quests, item histories — generated once at world creation, referenced forever |
| Community seeds | v3 | Curated scenario seed library supplements procedural generation. Human-validated world templates |
| Player-shared | v4 | Players publish worlds. Universe templates with genre packs. Cross-universe compatible worlds |
| Player-authored | v5 | Players create and share worlds from scratch. Moderation pipeline. Attribution system |

World content is the *output*. Genesis is the *process* that creates it.
Prompt engineering is the *craft* behind that process.
Concepts are the *thematic steering* that guides it.

## Quality & Evaluation
How we know the game is good.

| Phase | Version | What |
|-------|---------|------|
| Manual only | v1-v2.0 | Developer plays the game, decides if it's fun |
| Automated playtesting | v2.1 | LLM-persona agents run full sessions, multi-axis quality scoring |
| Human validation | v3 | Human playtesters calibrate automated metrics, structured feedback |
| Continuous monitoring | v4 | Production quality regression detection, A/B scenario evaluation |
| Full pipeline | v5 | Community feedback integrated into quality scoring |

## Therapeutic Depth
How the game supports personal growth — purely game mechanics until v4.

| Phase | Version | What |
|-------|---------|------|
| None | v1-v3 | Therapeutic stubs only. Personality traits exist as game mechanics, not therapy. |
| Personality depth | v4 | Radiant/Shadow traits, Big Five for NPCs and player character. Player modeling from interaction history. Still game mechanics, not therapy. |
| Healing framework | v5 | Reflection opportunities, therapeutic annotation, consent framework, crisis detection. Clinical review gates deployment. |

The key architecture decision: v1-v4 build **personality as game mechanic**.
NPCs have traits. Characters grow. Choices have emotional weight. But none of it
is "therapy" — it's just good character simulation. v5 adds the therapeutic lens
on top of an already-rich personality system.

## Safety
Content guardrails — from stubs to full consent framework.

| Phase | Version | What |
|-------|---------|------|
| Interfaces only | v1-v2.0 | Pre/post-generation hooks defined, not implemented |
| Pattern filtering | v2.1 | Basic content moderation — keyword/pattern blocking |
| Sentiment monitoring | v3 | Real-time player distress detection via input patterns |
| Crisis detection | v4 | Two-tier: pattern match + LLM classifier |
| Full consent | v5 | Player-defined boundaries, adjustable intensity, skip options, out-of-character safety response |

## Onboarding & Genesis
How players are introduced to the game and how new worlds are created within
their universe. This is the **player-facing experience** — the prompts they
answer, the phases they move through, the world that emerges around them.

| Phase | Version | What |
|-------|---------|------|
| Genesis-lite | v1 | 2-3 guided prompts seed a basic world. Simple questions: setting, tone, a starting location. |
| Genesis v2 | v2.0 | 7-phase Real→Strange arc. Player moves through escalating phases: grounded reality → subtle wrongness → full fantastic. Narrator-as-void-entity guides the journey. |
| Adaptive Genesis | v3 | Genesis adapts to returning players. "Create a new world" vs "continue in your existing universe." World creation can happen mid-game (discover a new continent). Player preferences from past sessions influence defaults. |
| Guided Genesis | v4 | TLC Monk personas optionally guide Genesis. A philosopher Monk helps shape world themes. A strategist Monk helps shape conflict. Player can accept or override suggestions. |
| Collaborative Genesis | v5 | Friends co-create a world together. Multi-player Genesis. Shared universe born from collective imagination. |

Genesis is NOT prompt engineering. It's a UX flow — what questions we ask, in
what order, with what guidance. The prompts themselves are built using whatever
prompt engineering techniques are available at that version (templated in v2.0,
versioned in v2.1, meta-prompted in v3, etc.), but Genesis defines the *sequence*.

## Concepts
Thematic steering of content generation. Concept maps, thematic networks, and
meta-concepts that guide what gets generated and how themes interconnect.

Drawn from Dukat's concept-driven generation: instead of linear scripts, a network
of themes (Betrayal, Redemption, Sacrifice, Hope, Tyranny) that activate, combine,
and steer narrative output.

| Phase | Version | What |
|-------|---------|------|
| None | v1-v2.0 | No concept system. Generation is prompt-driven without thematic steering. |
| Tone tags | v2.1 | Simple thematic tags (dark, hopeful, tense) attached to world elements. Quality evaluation checks tone consistency. 70/30 calibration. |
| Concept maps | v3 | Named concepts (Betrayal, Redemption, Sacrifice) with activation conditions and weights. Activated concepts influence prompt selection and narrative weighting. |
| Thematic resonance | v4 | Concepts echo across universes. A betrayal in Universe A weights betrayal-related concepts in Universe B. Resonance correlation engine. |
| Steering creation | v5 | Concept maps actively steer world generation. "I want a world about redemption" → redemption concept activates, weights all generation toward that theme. Meta-concepts (concepts about concepts) emerge from player behavior patterns. |

## Narrative Engine
How stories are told — from linear pipeline to multi-perspective generation.

| Phase | Version | What |
|-------|---------|------|
| Linear pipeline | v1 | 4-stage: Understand → Context → Generate → Deliver |
| Context-enriched | v2.0 | World memory, NPC relationships, consequence history fed into generation |
| Quality-steered | v2.1 | Tone calibration (70/30), lore consistency, quality metrics feed back into prompts |
| Beat-tracked | v3 | Narrative pacing, tension/release tracking, scene boundaries detected |
| Decision-matrix | v4 | 4-factor weighted generation (Narrative × World × Character × Randomness) — the same engine that powers gameplay turns. Emotional feedback loops. |
| Multi-perspective | v5 | TLC Monk narrative perspectives. Multiple AI personas contribute distinct narrative voices. Council governance of generated content. |

Note: v4's "Decision-matrix" is the same generation engine that powers Gameplay's
"Decision-matrix turns." They're one system, viewed from two angles — Gameplay
describes what the player experiences, Narrative Engine describes how generation
works under the hood.

## Prompt Engineering
How prompts are authored, versioned, and composed — the craft behind all generation.

This thread underpins both Genesis (world generation) and Narrative (storytelling).
As prompt techniques mature, both threads benefit.

| Phase | Version | What |
|-------|---------|------|
| Static prompts | v1 | Prompts are strings in code/config. Changed via PR. No version tracking. |
| Templated injection | v2.0 | Prompts use `{{variables}}` injected from world state. Still in code, but dynamic. |
| Versioned in Langfuse | v2.1 | Prompts managed in Langfuse. A/B comparison of prompt variants. Tone calibration (70/30) enforced via prompt engineering. Quality metrics tied to prompt versions. |
| Meta-prompts | v3 | Prompts that generate prompts. System adapts prompt construction to player context, world state, and narrative phase. Concept maps begin to influence prompt selection. |
| Prompt chains | v4 | Multi-step prompt sequences where each step's output feeds the next. Complex generation tasks (world creation, quest design) broken into chained prompts — each phase can be evaluated independently. |
| Self-improving | v5 | Quality feedback loops tune prompts automatically. Player preference modeling influences prompt construction. The system learns which prompts produce the best outcomes. |

Key techniques that phase in:

- **Meta-prompts** (v3): A higher-order prompt that writes the prompt for the next
  LLM call. "Given this world state and player history, construct a generation
  prompt that will produce..."

- **Concept maps** (v3→v4): Thematic networks (Betrayal, Redemption, Sacrifice)
  that influence which prompts are selected and how they're weighted. Concepts
  activate based on narrative context and player choices.

- **Prompt chains** (v4): Instead of one monolithic prompt, a sequence of focused
  prompts — each handling one aspect of generation. World creation becomes:
  geography prompt → culture prompt → history prompt → faction prompt. Each step
  sees the output of the previous step. Quality can be checked between steps.

- **Self-improving prompts** (v5): The evaluation pipeline scores output quality.
  Those scores feed back into prompt construction. Prompts that consistently
  produce high-quality output are weighted higher. The system gets better at
  generating over time, not through model upgrades, but through prompt evolution.

## UI / Client
The player-facing interface — from terminal to rich client.

| Phase | Version | What |
|-------|---------|------|
| Minimal HTML | v1-v2.0 | Bare test harness: text input, SSE output, no styling |
| Styled output | v2.1 | Formatted text, choice buttons, basic dark theme (playtester-ready) |
| Character sheet + map | v3 | Inventory, stats, world map, location browser (player-ready) |
| Voice + access | v4 | TTS narration, screen reader, mobile support |
| Full client | v5 | Desktop/mobile apps, offline mode, community features |

## Player Experience
The complete player journey — from discovering TTA to returning regularly.
Covers authentication, accounts, distribution, and the end-to-end experience
of getting into the game.

| Phase | Version | What |
|-------|---------|------|
| Dev terminal | v1-v2.0 | Developer plays via curl or bare HTML page. No auth. Session token only. docker-compose up to run. No other players. |
| Playtester invite | v2.1 | Invited playtesters access via styled web UI. Invite-link-based access (no accounts). Session-only. Feedback form built into the client. Still docker-compose. |
| Accounts + hosted | v3 | Player accounts (email/password). Character persistence across sessions — log in, see your characters, resume. Character sheet + world map UI. Story export. Hosted instance only (Fly.io). No self-host yet. Players get access via invite or waitlist. |
| Public launch | v4 | Full OAuth (Google, GitHub, Discord). Player dashboard. Self-host distribution (same Docker image). Character passport between universes. Open to everyone — no invite needed. Community story sharing begins. |
| Mature platform | v5 | Rich player profiles, privacy controls. Community reputation, shared universes. Central universe / P2P tracker. Mobile + desktop apps. Offline mode for self-host instances. |

The player experience thread spans three concerns:

**Authentication & Accounts**: No auth (v1-v2.1) → Email/password accounts (v3) → Full OAuth (v4) → Community profiles (v5)

**Distribution**: docker-compose for dev (v1-v2.1) → Hosted only (v3) → Hosted OR self-host Docker image (v4) → One-command install + app stores + P2P (v5)

**First-time experience**: Terminal/curl (v1-v2.0) → Invite link + styled UI (v2.1) → Account creation → Genesis onboarding → first turn (v3) → Returning player dashboard (v4) → Cross-universe character passport (v5)

The key architectural decision: **hosted and self-host are the same artifact.**
The Docker image that runs on Fly.io is the same image a player downloads at v4.
Self-host isn't a separate product — it's a deployment choice.
Accounts and hosted come first (v3). Self-host follows once the distribution
story is solid (v4).

## Infrastructure
How the game runs — from docker-compose to P2P mesh.

| Phase | Version | What |
|-------|---------|------|
| Docker compose | v1-v2.1 | Local dev: api + neo4j + redis + postgres + FMR |
| Concurrency stress | v2.1 | Measure single-process ceiling, identify bottlenecks |
| Production deploy | v3 | Fly.io, zero-downtime, CI/CD, horizontal scaling |
| Self-host | v4 | Players run their own instances. Docker-based distribution. P2P instance discovery. |
| P2P tracker | v5 | Central directory of online universes. Character routing between instances. |

## Sharing & Community
How players share their experiences.

| Phase | Version | What |
|-------|---------|------|
| None | v1-v2.1 | No sharing |
| Story export | v3 | Export session transcripts as PDF/ePub/web |
| Character passport | v4 | Export/import characters between compatible universes |
| Community templates | v5 | User-generated world templates, moderation, attribution |

## Scenes
The structured, replayable unit of narrative — a moment in time with setting,
characters, actions, and outcomes. Scenes are the bridge between "read someone's
story" and "experience someone's story." A scene is not a transcript. It's data
that the narrative engine can recreate, adapt, or reference.

Drawn from Adam's scene architecture work (D&D/theater-style scene design with
structured data: setting, cast, actions, stakes, resolution).

| Phase | Version | What |
|-------|---------|------|
| None | v1-v2.0 | No scene tracking. Narrative is continuous prose without formal boundaries. |
| Scene tracking | v2.1 | Engine records scene boundaries during play. Scenes are detected automatically (location change, cast change, narrative beat). Scene metadata stored: setting, characters present, actions taken, outcome. |
| Scene export | v3 | Players export scenes as structured data. "Relive this moment" — share a scene with another player, who can view it in their client. Scene compatibility validation across game systems. |
| Scene import | v4 | Import scenes from other players into your universe. Engine adapts the scene to your world (different NPCs, different locations, same dramatic structure). Scenes as procedural generation templates. |
| Scene library | v5 | Community-shared scene library. Curated scenes organized by genre, theme, emotional impact. Players build campaigns from scene templates. Scene remixing — take a scene from one universe, adapt it for another. |

Scenes connect to Sharing (export/import), Narrative Engine (beat tracking
identifies scene boundaries), and Concepts (thematic steering applies per-scene).
They're the unit of "I want to show you what happened in my game" — not a
wall of text, but a structured experience.
