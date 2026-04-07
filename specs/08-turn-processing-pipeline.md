# S08 — Turn Processing Pipeline

> **Status**: 📝 Draft
> **Level**: 2 — AI & Content
> **Dependencies**: S01 (Core Game Loop), S03 (World Model), S07 (LLM Integration)
> **Last Updated**: 2025-07-24

## 1 — Purpose

This spec defines the **end-to-end behavior** of processing a single player turn — from the moment the player submits input to the moment the narrative response finishes streaming.

This is a **behavior spec**. It describes *what happens*, not *which code does it*. Whether each stage is a separate LangGraph node, a function call, a microservice, or a single method is an **implementation decision** not made here.

The old TTA decomposed this into IPA → WBA → NGA. That decomposition had value, but it conflated behavior with architecture. The WBA, for example, was really a graph query layer — it never called an LLM. This spec separates the *behavioral stages* from any agent/component decomposition.

### Design values applied

| Value | Implication |
|---|---|
| **Fun** | Total turn time must stay under the player's boredom threshold. Streaming masks latency. |
| **Coherence** | Context assembly must gather enough world state to prevent contradictions. |
| **Player Agency** | The system must understand what the player *intended*, not just what they typed. |
| **Craftsmanship** | Every stage must be observable, testable, and gracefully degradable. |

---

## 2 — User Stories

### US-08.1 — Player submits a turn and gets a narrative response
> As a **player**, I want to type a free-form action (e.g. "I look behind the waterfall") and receive a narrative response that acknowledges my action, respects the world state, and advances the story.

### US-08.2 — Player's intent is understood even when ambiguous
> As a **player**, I want the game to make a reasonable interpretation of ambiguous input (e.g. "use it" → infer what "it" refers to from context) rather than asking me to rephrase.

### US-08.3 — World state is reflected in narrative
> As a **player**, I want the narrative to reference things I've done, items I carry, and NPCs I've met — not contradict prior events or invent items I don't have.

### US-08.4 — Response streams progressively
> As a **player**, I want to see the story appear word-by-word rather than waiting for the entire response, so the experience feels alive and responsive.

### US-08.5 — Developer can trace a turn end-to-end
> As a **developer**, I want to see the full journey of a turn — input parsing, context assembly, generation prompt, raw output, post-processing — in a single trace, so I can debug quality issues.

### US-08.6 — Broken input doesn't crash the session
> As a **player**, I want the game to handle my weird input (empty string, 10,000 characters, emoji-only, profanity) gracefully rather than breaking.

### US-08.7 — Slow LLM doesn't freeze the game
> As a **player**, I want to know the game is thinking (typing indicator, partial stream) rather than facing a frozen screen when the AI takes longer than usual.

---

## 3 — Pipeline Overview

A player turn flows through four behavioral stages:

```
┌─────────────┐    ┌──────────────────┐    ┌──────────────┐    ┌────────────┐
│   INPUT     │───▶│    CONTEXT       │───▶│  GENERATION  │───▶│  DELIVERY  │
│ UNDERSTAND  │    │    ASSEMBLY      │    │              │    │            │
└─────────────┘    └──────────────────┘    └──────────────┘    └────────────┘
  Extract meaning    Gather world state     Produce narrative    Stream to player
  from player input  for generation         prose from context   via SSE
```

Each stage has defined **inputs**, **outputs**, and **failure modes**. The contracts between stages are specified in §7.

---

## 4 — Stage 1: Input Understanding

### 4.1 — What this stage does

Transform raw player text into structured understanding of player intent. This is the system's "reading comprehension" step.

### 4.2 — Inputs

| Field | Type | Description |
|---|---|---|
| `raw_input` | string | The player's typed text, as-is |
| `session_id` | string | Current session identifier |
| `turn_number` | integer | Sequential turn count |
| `recent_history` | list[message] | Last 3-5 conversation exchanges for reference resolution |

### 4.3 — Outputs: the Understanding object

| Field | Type | Description | Example |
|---|---|---|---|
| `intent` | enum | Primary action category | `explore`, `interact`, `use_item`, `examine`, `speak`, `rest`, `other` |
| `entities` | list[entity] | Referenced game objects | `[{"name": "old key", "type": "item", "resolved_id": "item-42"}]` |
| `target` | entity \| null | Primary target of the action | `{"name": "wooden door", "type": "object", "resolved_id": "obj-17"}` |
| `emotional_tone` | enum | Detected emotional register | `neutral`, `anxious`, `curious`, `frustrated`, `playful`, `distressed` |
| `confidence` | float | System's confidence in the interpretation | `0.0` – `1.0` |
| `raw_input` | string | Original text, preserved for generation | "I try the old key on the wooden door" |
| `is_meta` | boolean | Whether the input is a meta/OOC command | `false` |
| `references` | list[reference] | Resolved anaphora ("it", "them", "her") | `[{"pronoun": "it", "resolved_to": "old key"}]` |

### 4.4 — Functional requirements

**FR-08.01**: The system SHALL classify player input into one of the defined intent categories. If no category fits, the intent SHALL be `other`.

**FR-08.02**: The system SHALL extract named entities from the input and attempt to resolve them against the current world state (inventory items, nearby NPCs, visible objects). Unresolved entities SHALL be flagged for the generation stage to handle narratively.

**FR-08.03**: The system SHALL detect anaphoric references ("it", "them", "the door") and resolve them using recent conversation history. If resolution is ambiguous, the system SHALL pick the most contextually likely referent and set `confidence` below 0.7.

**FR-08.04**: The system SHALL detect the emotional tone of the input. This informs the generation stage's narrative tone (e.g. a frustrated player might receive a more encouraging narrative).

**FR-08.05**: The system SHALL detect meta-commands (e.g. "save game", "what can I do?", "help") and route them separately from narrative input. Meta-commands do not flow through the full pipeline.

**FR-08.06**: The system SHALL validate input length. Inputs exceeding the maximum length (configurable, default: 2000 characters) SHALL be truncated with a player-facing note.

**FR-08.07**: Empty or whitespace-only input SHALL be handled gracefully — the system responds with a gentle narrative prompt (e.g. "You pause, considering your options…") without treating it as an error.

### 4.5 — LLM usage in this stage

Input understanding MAY use the `classification` or `extraction` model roles (see S07). For simple intents and well-structured input, rule-based parsing may suffice. The spec does not prescribe when to use LLM vs. rules — that's an implementation decision.

**FR-08.08**: If LLM-based understanding is used, it SHALL use the `classification` role with structured output (JSON mode) and low temperature (≤0.2) for deterministic results.

### 4.6 — Failure modes

| Failure | Detection | Handling |
|---|---|---|
| **Unparseable input** | No intent detected, confidence < 0.3 | Set intent to `other`, pass raw input to generation with a flag indicating low-confidence parse |
| **Entity resolution failure** | Entity mentioned but not found in world state | Include unresolved entity in output; generation stage handles it narratively ("You don't see anything like that here") |
| **LLM call failure** | Timeout or error from classification model | Fall back to keyword-based intent detection. If that also fails, pass raw input with `intent: other` |

---

## 5 — Stage 2: Context Assembly

### 5.1 — What this stage does

Gather all relevant information from the game world so the generation stage can produce coherent, grounded narrative. This stage makes **no LLM calls** — it is a data retrieval and structuring step.

### 5.2 — Inputs

| Field | Type | Source |
|---|---|---|
| Understanding object | object | Stage 1 output |
| `session_id` | string | Turn metadata |
| `player_id` | string | Session metadata |

### 5.3 — Outputs: the Context object

| Field | Description | Source |
|---|---|---|
| `location` | Current location details (name, description, exits, atmosphere) | World graph (Neo4j) |
| `inventory` | Player's current items with descriptions | Player data |
| `nearby_npcs` | NPCs present in the current location, with personality summaries and relationship to player | World graph |
| `nearby_objects` | Interactable objects in the current location | World graph |
| `recent_events` | Last 3-5 significant events in the session (summarized) | Session history |
| `conversation_history` | Recent exchanges, potentially summarized for length | Session history |
| `active_quests` | Current objectives and their progress | Player data |
| `world_time` | In-game time of day, weather, ambient conditions | World state |
| `character_state` | Player character's physical/emotional state | Player data |
| `relevant_lore` | Background information relevant to the current scene | World graph |
| `genre_context` | Genre, tone, and narrative style parameters | Session configuration |

### 5.4 — Functional requirements

**FR-08.09**: The system SHALL query the world graph for the player's current location and all connected entities (NPCs, objects, exits) within the current scene.

**FR-08.10**: The system SHALL retrieve the player's inventory and character state from the player data store.

**FR-08.11**: The system SHALL retrieve the last N conversation exchanges (configurable, default: 10) from the session history. If the history is long, it SHALL include a summary of older exchanges (produced by the `summarization` model role, see S07) and the full text of the most recent 3 exchanges.

**FR-08.12**: The context SHALL include only information **relevant to the current action**. If the player says "look at the door", the system should prioritize door-related context over distant NPC backstories. Relevance filtering is based on the Understanding object from Stage 1.

**FR-08.13**: The system SHALL compute a token estimate of the assembled context and ensure it fits within the generation model's context budget (per S07 §5). If it exceeds the budget, the system SHALL truncate according to S07's priority tiers.

**FR-08.14**: Context assembly SHALL complete within a bounded time (configurable, default: 500ms). If database queries take longer, the system SHALL proceed with partial context and log a performance warning.

### 5.5 — Context relevance

Not all world state is equally relevant. Context assembly should prioritize:

1. **Directly referenced**: Entities the player named or resolved references point to (highest priority).
2. **Scene-present**: NPCs and objects in the current location.
3. **Recently active**: NPCs or items involved in the last 2-3 turns.
4. **Narratively adjacent**: Lore, quests, or events connected to the current scene.
5. **Background**: General world state, time of day, weather (lowest priority).

**FR-08.15**: The system SHALL tag each context element with a relevance tier so that the token budget truncation (FR-08.13) removes the least relevant items first.

### 5.6 — Failure modes

| Failure | Detection | Handling |
|---|---|---|
| **World graph unavailable** | Database connection failure | Use cached location data if available. If no cache, generate with minimal context (player input + conversation history only). Log critical alert. |
| **Player data unavailable** | Data store query failure | Generate without inventory/character state. The narrative may be less grounded but still playable. |
| **Slow queries** | Exceeded 500ms budget | Return whatever context was retrieved so far. Mark context as `partial` in the context object. |

---

## 6 — Stage 3: Narrative Generation

### 6.1 — What this stage does

Transform the Understanding + Context into narrative prose that responds to the player's action, maintains world coherence, and advances the story.

### 6.2 — Inputs

| Field | Type | Source |
|---|---|---|
| Understanding object | object | Stage 1 |
| Context object | object | Stage 2 |
| Prompt template + variables | object | Prompt registry (S09) |
| Generation parameters | object | S07 role defaults + template overrides |

### 6.3 — Outputs: the Generation result

| Field | Type | Description |
|---|---|---|
| `narrative_text` | string | The prose response to the player |
| `world_state_updates` | list[update] | Changes to world state implied by this turn (item moved, NPC reacted, door opened) |
| `turn_metadata` | object | Token counts, model used, latency, cost, prompt version |
| `suggested_actions` | list[string] \| null | Optional hints for what the player might do next |
| `narrative_tone` | enum | The tone of the generated response (for consistency tracking) |

### 6.4 — Functional requirements

**FR-08.16**: The system SHALL assemble a prompt from the registered template for narrative generation, injecting the Understanding and Context as template variables (per S09).

**FR-08.17**: The system SHALL call the LLM using the `generation` model role (per S07) with streaming enabled.

**FR-08.18**: The generated narrative SHALL:
- Acknowledge the player's action (not ignore it).
- Be consistent with the assembled context (not contradict known world state).
- Advance the story or provide meaningful new information.
- Match the configured genre tone and narrative style.
- Be between 50 and 500 words (configurable per genre/style).

**FR-08.19**: The system SHALL extract world-state updates from the generation. There are two strategies for this:
1. **Inline extraction**: Parse the narrative for implied state changes (e.g. "The door swings open" → `door.state = open`).
2. **Separate LLM call**: Ask a second LLM call (using `extraction` role) to identify state changes from the narrative text.
The strategy is an implementation choice. The spec requires that state changes are detected and applied.

**FR-08.20**: World-state updates SHALL be validated before application. An update that contradicts hard constraints (e.g. opening a door that requires a key the player doesn't have) SHALL be rejected, and the generation SHALL be retried with a note about the constraint.

**FR-08.21**: The system MAY generate 1-3 suggested actions to hint at what the player could do next. These are optional and depend on the genre/style configuration.

### 6.5 — Generation quality guardrails

**FR-08.22**: The system SHALL detect and reject narrative that:
- Is empty or substantially shorter than the minimum length.
- Contains obvious repetition (same sentence or phrase repeated 3+ times).
- Breaks the fourth wall or references itself as an AI (unless the genre explicitly calls for it).
- References game objects, NPCs, or locations that are not in the assembled context.

**FR-08.23**: On quality rejection, the system SHALL retry generation once with the same context but a different random seed. If the retry also fails quality checks, deliver the best-of-two response with a quality warning logged.

### 6.6 — Failure modes

| Failure | Detection | Handling |
|---|---|---|
| **Generation LLM failure** | All tiers fail (per S07 §10.2) | Return pre-written "story pauses" message. Preserve player input for retry. |
| **Quality check failure** | Generated text fails FR-08.22 checks | Retry once. If both attempts fail, deliver the better response with a quality flag. |
| **State update conflict** | World-state update contradicts constraints | Reject the conflicting update. Retry generation with constraint reminder in prompt. |
| **Excessive length** | Response exceeds max word count | Truncate at the last complete sentence within the limit. |

---

## 7 — Stage 4: Delivery

### 7.1 — What this stage does

Stream the generated narrative to the player's client and finalize the turn's side effects (state updates, history persistence, observability).

### 7.2 — Functional requirements

**FR-08.24**: Narrative tokens SHALL be streamed to the player via SSE as they are generated (per S07 §7). The player sees text appearing progressively, not a loading spinner followed by a text block.

**FR-08.25**: While streaming, the system SHALL buffer tokens to ensure partial delivery is at word boundaries (not mid-word), unless the client explicitly opts into character-level streaming.

**FR-08.26**: After streaming completes, the system SHALL emit a `turn_complete` SSE event containing:
- Turn ID
- Total token count
- Suggested actions (if any)
- Any player-facing metadata (e.g. "item acquired" notifications)

**FR-08.27**: After delivery, the system SHALL persist:
1. The player's input (raw text).
2. The Understanding object.
3. The full narrative response.
4. World-state updates applied.
5. Turn metadata (timing, model used, cost, prompt version).

**FR-08.28**: World-state updates SHALL be applied atomically after generation completes — not during streaming. This prevents partial state corruption if streaming is interrupted.

**FR-08.29**: The complete turn (all stages) SHALL be recorded as a single Langfuse trace with child spans for each stage.

---

## 8 — Inter-Stage Contracts

### 8.1 — Data flow summary

```
Stage 1 (Input Understanding)
  Input:  raw_input, session_id, turn_number, recent_history
  Output: Understanding { intent, entities, target, emotional_tone, confidence, ... }

Stage 2 (Context Assembly)
  Input:  Understanding, session_id, player_id
  Output: Context { location, inventory, nearby_npcs, conversation_history, ... }

Stage 3 (Narrative Generation)
  Input:  Understanding, Context, prompt_template, generation_params
  Output: Generation { narrative_text, world_state_updates, turn_metadata, ... }

Stage 4 (Delivery)
  Input:  Generation, session_id, turn_id
  Output: SSE stream to client, persisted turn record
```

### 8.2 — Contract enforcement

**FR-08.30**: Each inter-stage contract SHALL be defined as a typed schema. If a stage produces output that does not conform to the schema, the pipeline SHALL log an error and attempt recovery (e.g. use defaults for missing fields).

**FR-08.31**: The pipeline SHALL be instrumented to record the latency of each stage independently, so that performance bottlenecks can be identified.

---

## 9 — Latency Budget

### 9.1 — Turn time targets

| Metric | Target | Maximum | Notes |
|---|---|---|---|
| **Total turn time** (input to first streamed token) | < 2 seconds | 5 seconds | This is the "responsiveness" metric players feel most. |
| **Total turn time** (input to stream complete) | < 8 seconds | 15 seconds | Full response delivered. |
| **Stage 1** (Input Understanding) | < 300ms | 1 second | Should be fast — classification or rule-based. |
| **Stage 2** (Context Assembly) | < 500ms | 1 second | Database queries. No LLM calls. |
| **Stage 3** (Generation — TTFT) | < 1.5 seconds | 4 seconds | Time to first token from LLM. |
| **Stage 4** (Delivery overhead) | < 50ms | 200ms | SSE infrastructure overhead, negligible. |

**FR-08.32**: The system SHALL measure and report per-stage latencies for every turn. Turns exceeding the maximum total time SHALL trigger a performance warning in the observability backend.

**FR-08.33**: If Stage 1 or Stage 2 exceeds its target, the pipeline SHALL proceed with whatever results are available (partial understanding, partial context) rather than blocking.

### 9.2 — Player experience during wait

**FR-08.34**: While the pipeline is processing (before the first token streams), the system SHALL send a `thinking` SSE event to the client so the UI can show a typing indicator or equivalent.

**FR-08.35**: If no token has been streamed within 3 seconds of the `thinking` event, the system SHALL send a `still_thinking` event with an estimated wait time, so the player knows the system hasn't frozen.

---

## 10 — Concurrency

### 10.1 — Can stages overlap?

**FR-08.36**: Stage 1 and Stage 2 MAY execute concurrently if they are independent. In practice, Stage 2 depends on Stage 1's entity resolution to know what context to prioritize, so full parallelism may not be possible — but partial overlap is allowed (e.g. start loading location data while entity extraction is still running).

**FR-08.37**: Stage 3 (Generation) and Stage 4 (Delivery) SHALL overlap: streaming begins as soon as the first token is generated. Delivery does not wait for generation to complete.

**FR-08.38**: A player SHALL NOT be able to submit a new turn while the current turn is still being processed. The client SHALL disable input during pipeline execution. The server SHALL reject concurrent turns for the same session.

### 10.2 — Idempotency

**FR-08.39**: If a turn submission is received twice (e.g. due to network retry), the system SHALL detect the duplicate (via turn ID or idempotency key) and return the result of the original turn, not process the input twice.

---

## 11 — Error Handling Summary

### 11.1 — Per-stage error handling

| Stage | Error | Player experience | System behavior |
|---|---|---|---|
| **1 — Understanding** | Total failure | Transparent — game still responds | Generate with raw input, `intent: other`. Less tailored response. |
| **2 — Context** | DB unavailable | Transparent — game still responds | Generate with minimal context. Response may be less grounded. |
| **3 — Generation** | All LLM tiers fail | Visible — "the story pauses" | Preserve input, allow retry, critical alert. |
| **3 — Generation** | Quality check fail | Transparent | Best-effort delivery with quality warning logged. |
| **4 — Delivery** | Client disconnect | N/A — player left | Save partial response, mark turn as partial. |
| **4 — Delivery** | State persistence fail | Transparent — game continues | Retry persistence async. If retry fails, log critical error — the turn's side effects are lost. |

### 11.2 — Cascading failure

**FR-08.40**: If Stages 1 and 2 both fail, the system SHALL still attempt generation with just the raw input and system prompt. The result will be lower quality but the session stays alive.

**FR-08.41**: The system SHALL NOT retry the entire pipeline on failure. Each stage handles its own errors independently. Only Stage 3 (generation) uses the multi-tier fallback from S07.

---

## 12 — Pipeline Observability

**FR-08.42**: Each turn SHALL produce a single Langfuse trace containing:
- A root span for the entire turn.
- Child spans for each pipeline stage (Understanding, Context, Generation, Delivery).
- Within the Generation span: the LLM call details (prompt, completion, model, tokens, cost).
- Tags: session ID, turn number, intent detected, model role used, fallback tier.

**FR-08.43**: The trace SHALL include the full Understanding and Context objects as span attributes (or linked metadata), so that a developer can reconstruct exactly what the generation model "saw".

**FR-08.44**: The system SHALL log the following per-turn summary:
```json
{
  "turn_id": "t-abc123",
  "session_id": "s-xyz789",
  "turn_number": 7,
  "input_length_chars": 42,
  "intent": "explore",
  "context_token_count": 3200,
  "generation_model": "gpt-4o-mini",
  "generation_tier": "primary",
  "output_length_chars": 380,
  "total_latency_ms": 2450,
  "stage_latencies_ms": {
    "understanding": 180,
    "context_assembly": 320,
    "generation_ttft": 1200,
    "generation_total": 2400,
    "delivery": 50
  },
  "cost_usd": 0.0023
}
```

---

## 13 — Edge Cases

### EC-08.1 — Player input references something from 30 turns ago
The system should attempt to find the referenced entity in the full session history, not just recent turns. If the entity is found in the summarized history, include it in context. If not found at all, the narrative should acknowledge the reference naturally ("You try to remember, but the details are hazy…").

### EC-08.2 — Player tries to do something impossible
"I fly to the moon." The system should not hallucinate moon-flying ability. The Understanding stage detects an action; the Context stage reveals no flying ability; the Generation stage produces a narrative that redirects ("You look up at the moon, wishing you could reach it…").

### EC-08.3 — Player submits pure gibberish
"asdfghjkl". Intent detection should return `other` with low confidence. The narrative should respond in-character ("You mutter something incomprehensible, and the old man gives you a puzzled look.").

### EC-08.4 — Player submits input that matches a game object name exactly
"Key." The system should interpret this as examining or using the key, depending on context (if the player is in front of a lock, probably "use key on lock"; if just standing around, "examine key").

### EC-08.5 — Context assembly returns no NPCs, no objects, empty location
The player is in a completely empty/undescribed location (possible in early development). Generation should still produce a response, even if it's atmospheric ("You stand in an empty clearing. The air is still.").

### EC-08.6 — Two rapid turns submitted
Per FR-08.38, the second turn is rejected. But what if the first turn is almost done? The system should complete the first turn, then process the second. If the second was rejected, the client should allow resubmission after the first completes.

### EC-08.7 — Player's action changes the location
"I walk through the door." After generation, the world-state update includes a location change. The next turn's context assembly should use the new location. The state update must be applied before the next turn starts.

---

## 14 — Acceptance Criteria

### AC-08.1 — End-to-end turn processing
- [ ] A player can submit text input and receive a streaming narrative response.
- [ ] The response acknowledges the player's action.
- [ ] The response is consistent with the current world state.
- [ ] Total time from input to first streamed token is under 5 seconds (p95).

### AC-08.2 — Input understanding
- [ ] Player intent is correctly classified for common action types (explore, interact, use item, examine, speak).
- [ ] Entity references ("the key", "it", "old man") are resolved against world state.
- [ ] Gibberish and empty input produce graceful responses, not errors.
- [ ] Meta-commands are detected and routed separately.

### AC-08.3 — Context assembly
- [ ] The generation model receives relevant world state (location, NPCs, inventory).
- [ ] Context is filtered by relevance to the current action.
- [ ] Context fits within the generation model's token budget.
- [ ] Context assembly completes within 1 second (p95).

### AC-08.4 — Generation quality
- [ ] Narrative does not reference objects/NPCs absent from context.
- [ ] Narrative matches the configured genre/tone.
- [ ] Repetitive or empty output is detected and retried.
- [ ] World-state updates are extracted and validated.

### AC-08.5 — Delivery
- [ ] Tokens stream to the client via SSE as they are generated.
- [ ] A `thinking` indicator is sent before the first token.
- [ ] The `turn_complete` event includes all required metadata.
- [ ] Turns are persisted to the session history.

### AC-08.6 — Error resilience
- [ ] If input understanding fails, the turn still produces a response.
- [ ] If the database is down, the turn still produces a response (lower quality).
- [ ] If all LLM tiers fail, the player sees a graceful message, not an error.
- [ ] Duplicate turn submissions are deduplicated.

### AC-08.7 — Observability
- [ ] Every turn is traceable in Langfuse with per-stage timing.
- [ ] The full Understanding and Context are recoverable from the trace.
- [ ] Per-turn cost is recorded.

---

## 15 — Open Questions

| # | Question | Impact | Resolution needed by |
|---|---|---|---|
| Q-08.1 | Should input understanding run in parallel with basic context pre-fetching (e.g. load current location while classifying intent)? | Performance optimization — could shave 200-300ms off turn time | Before performance optimization pass |
| Q-08.2 | How should the system handle multi-step actions ("I pick up the key and unlock the door")? As one turn or two? | Affects pipeline complexity significantly | Before alpha playtest |
| Q-08.3 | Should world-state updates be confirmed with the player before applying? ("You opened the door. [Continue?]") | Affects player agency vs. flow | Before S01 finalization |
| Q-08.4 | What is the minimum viable context for generation? Can we define a fallback context that's always available (just location name + last exchange)? | Affects error resilience design | Before S03 finalization |

---

## Appendix A — Glossary

| Term | Definition |
|---|---|
| **Turn** | One player input + one system response. The atomic unit of gameplay. |
| **Understanding** | Structured interpretation of player input (intent, entities, emotion, references). |
| **Context** | Assembled world state and history provided to the generation model. |
| **TTFT** | Time to first token — latency from request to first streamed output. |
| **SSE** | Server-Sent Events — the protocol for streaming tokens to the client. |
| **World-state update** | A change to the game world implied by the turn (item moved, door opened, NPC reacted). |

## Appendix B — Intent Categories

| Intent | Description | Example inputs |
|---|---|---|
| `explore` | Player wants to move or look around | "Go north", "Look around", "What's over there?" |
| `interact` | Player wants to interact with an NPC | "Talk to the old man", "Ask her about the key" |
| `use_item` | Player wants to use an inventory item | "Use the key on the door", "Drink the potion" |
| `examine` | Player wants to inspect something closely | "Look at the painting", "Read the inscription" |
| `speak` | Player says something in-character | "Hello, my name is…", "'I come in peace'" |
| `rest` | Player wants to wait, rest, or pass time | "Wait until morning", "Take a nap", "Rest" |
| `other` | Unclassified or ambiguous | "Hmm", "asdfg", "I wonder what happens if…" |
