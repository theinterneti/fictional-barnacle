# LLM Integration + Turn Processing Pipeline — Component Technical Plan

> **Phase**: SDD Phase 2 — Component Plan
> **Scope**: LLM wrapper (`src/tta/llm/`), Pipeline stages (`src/tta/pipeline/`)
> **Input specs**: S07 (LLM Integration), S08 (Turn Processing Pipeline)
> **Parent plan**: `plans/system.md` (authoritative for all cross-cutting decisions)
> **Implementation wave**: Wave 2
> **Status**: 📝 Draft
> **Last Updated**: 2026-04-07

---

## 0. Resolved Conflicts and Normative Decisions

Before diving into implementation details, this section resolves spec-level conflicts
that the system plan left to this component plan.

### 0.1 — Streaming Architecture: Buffer-Then-Stream

**Decision**: v1 uses **buffer-then-stream** as specified in system.md §2.4.

The LLM is called with `stream=True` to collect tokens incrementally (improving
internal latency tracking), but all tokens are accumulated into a buffer. The
post-generation safety hook inspects the complete response. Only after approval does
the delivery stage stream tokens to the client via SSE.

This means:
- S07 FR-07.23 ("forward tokens to the player via SSE as they arrive") is **amended
  for v1**: tokens stream from the *buffer*, not from the live LLM stream.
- S08 FR-08.37 ("Stage 3 and Stage 4 SHALL overlap") is **deferred to v2**: in v1
  delivery starts only after generation completes.
- TTFT is measured from turn submission to the first `narrative_token` SSE event — this
  includes generation time + safety check. The 3s p95 TTFT target (system.md §5.1) is
  aspirational for v1; the `thinking` SSE event mitigates perceived delay.

### 0.2 — SSE Event Contract (Authoritative for This Plan)

The SSE event names and payload shapes are defined in system.md §4.2. This plan
uses those names exactly:

| Event | Payload | When emitted |
|-------|---------|-------------|
| `turn_start` | `{turn_number, timestamp}` | Immediately after pipeline begins |
| `thinking` | `{}` | After `turn_start`, before first token |
| `still_thinking` | `{elapsed_ms}` | If >3s since `thinking` with no tokens |
| `narrative_token` | `{token}` | Per word-boundary token from buffer |
| `world_update` | `{changes: [{type, entity_id, ...}]}` | After all tokens, before `turn_complete` |
| `turn_complete` | `{turn_number, model_used, latency_ms, suggested_actions}` | Final event |
| `error` | `{code, message}` | On pipeline failure |
| `keepalive` | `{}` | Every 15s on idle SSE connections |

S07 §7.1's `token`/`done` examples are informational — system.md §4.2 is
authoritative.

### 0.3 — Turn Lifecycle (Authoritative for This Plan)

A turn row is the durable record. Status transitions:

```
        ┌──────────┐    success    ┌──────────┐
  POST  │processing│──────────────▶│ complete │
 /turns │          │               └──────────┘
        └────┬─────┘
             │ all tiers fail
             ▼
        ┌──────────┐
        │  failed  │
        └──────────┘
```

Lifecycle:
1. `POST /turns` creates a row: `INSERT INTO turns (id, session_id, turn_number,
   idempotency_key, status, player_input) VALUES (...)` with `status='processing'`.
2. `turn_number` is assigned as `max(turn_number) + 1` for the session, within the
   same transaction.
3. Concurrent-turn guard: the INSERT transaction first runs `SELECT id FROM turns
   WHERE session_id=$1 AND status='processing' FOR UPDATE`. If a row exists, return
   `409 Conflict`.
4. Duplicate idempotency key: the `UNIQUE(session_id, idempotency_key)` constraint
   catches this. On conflict, return the existing `turn_id` and `stream_url`.
5. On pipeline success: `UPDATE turns SET status='complete', narrative_output=$2,
   parsed_intent=$3, world_context=$4, model_used=$5, latency_ms=$6, token_count=$7,
   completed_at=now() WHERE id=$1`.
6. On pipeline failure: `UPDATE turns SET status='failed', completed_at=now()
   WHERE id=$1`.
7. On client disconnect mid-stream: buffer is already complete (buffer-then-stream),
   so the turn record is finalized as `complete` regardless. Delivery is best-effort.

---

## 1. LiteLLM Wrapper Design

### 1.1 — Module Structure

```
src/tta/llm/
├── __init__.py
├── client.py        # LiteLLMClient implementation
├── roles.py         # ModelRole enum, ModelRoleConfig, role registry
├── errors.py        # Error classification
└── testing.py       # MockLLMClient for CI
```

### 1.2 — LLMClient Implementation

The `LLMClient` protocol is defined in system.md §4.4 and is normative. This section
specifies the `LiteLLMClient` class that implements it.

```python
class LiteLLMClient:
    """LiteLLM-backed implementation of LLMClient protocol."""

    def __init__(
        self,
        role_config: dict[ModelRole, ModelRoleConfig],
        langfuse_client: Langfuse | None = None,
    ) -> None: ...

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse: ...

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse: ...
```

**Return type note**: both `generate()` and `stream()` return `LLMResponse`, not raw
strings. In v1's buffer-then-stream architecture, `stream()` collects the full
response internally and returns the same `LLMResponse` envelope as `generate()`.
The `stream=True` flag to LiteLLM is still used — it enables incremental token
collection (better timeout behavior, internal latency tracking) — but the caller
receives a complete response.

```python
class LLMResponse(BaseModel):
    """Uniform response envelope (FR-07.02)."""
    content: str                   # Generated text
    model_used: str                # Actual model that served the request
    token_count: TokenCount
    latency_ms: float              # Pipeline-measured latency
    tier_used: Literal["primary", "fallback"] = "primary"
    trace_id: str = ""             # Langfuse trace ID (empty if tracing disabled)
    cost_usd: float = 0.0         # Estimated cost from LiteLLM

class TokenCount(BaseModel):
    prompt: int
    completion: int
```

### 1.3 — Model Role Configuration

```python
class ModelRoleConfig(BaseModel):
    """Per-role model configuration (FR-07.04)."""
    primary_model: str             # e.g. "anthropic/claude-sonnet-4-20250514"
    fallback_model: str | None     # e.g. "anthropic/claude-haiku-4-20250514"

    # Generation parameter defaults (FR-07.31)
    temperature: float = 0.8
    top_p: float = 0.95
    max_tokens: int = 1024
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0

    # Timeout (FR-07.10)
    timeout_seconds: float = 10.0

    # Context window sizes (for token budget computation)
    primary_context_window: int = 200_000
    fallback_context_window: int | None = None  # Inferred from model if not set
```

Default role configurations loaded from environment/settings:

| Role | Primary | Fallback | Temperature | Max Tokens | Timeout |
|------|---------|----------|-------------|------------|---------|
| `generation` | `claude-sonnet-4-20250514` | `claude-haiku-4-20250514` | 0.8 | 1024 | 10s |
| `classification` | `claude-haiku-4-20250514` | — | 0.1 | 256 | 5s |
| `extraction` | `claude-haiku-4-20250514` | — | 0.2 | 512 | 5s |
| `summarization` | `claude-haiku-4-20250514` | — | 0.3 | 512 | 8s |

Classification and extraction use only Haiku — they're fast, cheap, and tone doesn't
matter. Only `generation` has a same-family fallback chain to preserve narrative voice
(system.md §6.1).

### 1.4 — Fallback Chain

```
generation:    claude-sonnet → claude-haiku → graceful failure
classification: claude-haiku → keyword fallback (not an LLM tier)
extraction:    claude-haiku → graceful failure (no updates extracted)
```

Each tier is a fresh request with the same prompt (FR-07.08). If falling back to a
model with a smaller context window, the wrapper re-computes the token budget and
truncates context before sending (EC-07.5, EC-07.9).

**Graceful failure**: when all LLM tiers fail, `generate()`/`stream()` raises
`AllTiersFailedError`. The pipeline orchestrator catches this and returns the
"story pauses" message.

### 1.5 — Retry Strategy (tenacity)

Retry is per-tier — each model attempt has its own retry envelope. Fallback to the
next tier happens only after retries are exhausted.

```python
@retry(
    retry=retry_if_exception(is_transient_error),
    stop=stop_after_attempt(3),         # 1 initial + 2 retries
    wait=wait_exponential(multiplier=1, min=1, max=4) + wait_random(0, 0.5),
    before_sleep=log_retry_attempt,
)
async def _call_model(self, model: str, messages, params) -> LLMResponse:
    ...
```

System.md §1.1 mandates tenacity for retry — no custom retry logic. The `retry`
decorator handles transient errors only; terminal errors propagate immediately.

### 1.6 — Error Classification

| Category | Errors | Retryable? | Behavior |
|----------|--------|------------|----------|
| **Transient** | HTTP 429, 500, 502, 503; `TimeoutError`; `ConnectionError` | Yes | Retry with backoff, then fallback |
| **Empty/malformed** | Empty response; JSON parse failure on structured output | Partial | Retry once on same tier (different seed), then fallback |
| **Content filtered** | Provider safety filter rejection | Partial | Log, retry once with same prompt, then fallback |
| **Configuration** | HTTP 401, 403, 404 (model not found); invalid API key | No | Fail immediately with `ConfigurationError`. Log critical alert. |
| **Budget** | Session cost cap exceeded | No | Raise `BudgetExceededError`. Handled by orchestrator. |

```python
def is_transient_error(exc: BaseException) -> bool:
    """Return True for errors that warrant retry."""
    if isinstance(exc, litellm.RateLimitError):
        return True
    if isinstance(exc, litellm.ServiceUnavailableError):
        return True
    if isinstance(exc, (TimeoutError, httpx.ConnectError)):
        return True
    if isinstance(exc, EmptyResponseError):
        return True
    return False

def is_configuration_error(exc: BaseException) -> bool:
    """Return True for errors that should NOT be retried."""
    if isinstance(exc, litellm.AuthenticationError):
        return True
    if isinstance(exc, litellm.NotFoundError):
        return True
    return False
```

### 1.7 — Circuit Breaking

System.md §1.4 says "do NOT build custom retry/circuit-breaker logic" and §1.1
mandates tenacity for retry. Circuit-breaking behavior (FR-07.11) is implemented via
a lightweight cooldown tracker — not a full circuit-breaker framework:

```python
class ModelCooldown:
    """Track per-model failure counts. Skip models in cooldown."""

    def __init__(self, threshold: int = 5, window_s: int = 60, cooldown_s: int = 30):
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._cooldown_until: dict[str, float] = {}
        ...

    def record_failure(self, model: str) -> None: ...
    def is_cooled_down(self, model: str) -> bool: ...
    def record_success(self, model: str) -> None: ...
```

If a model is in cooldown, the fallback chain skips it entirely. This is a data
structure, not retry logic — tenacity still handles the actual retry/backoff.

### 1.8 — Cost Tracking

Per-call cost is computed from LiteLLM's `response.usage` and a pricing table:

```python
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # model_name: (input_cost_per_1k, output_cost_per_1k)
    "anthropic/claude-sonnet-4-20250514": (0.003, 0.015),
    "anthropic/claude-haiku-4-20250514": (0.00025, 0.00125),
}
```

Cost data is:
1. Returned in `LLMResponse.cost_usd`
2. Pushed to Langfuse as a generation event attribute
3. Accumulated per-session by the orchestrator (see §7.4)

### 1.9 — Langfuse Integration

Every LLM call is recorded as a Langfuse **generation** within the turn's trace:

```python
generation = trace.generation(
    name=f"llm_{role.value}",
    model=response.model_used,
    input=messages,
    output=response.text,
    usage={"prompt_tokens": tc.prompt, "completion_tokens": tc.completion},
    metadata={"tier": response.tier_used, "cost_usd": response.cost_usd},
)
```

The `trace_id` is passed into `LiteLLMClient` from the pipeline orchestrator so all
calls within a turn are grouped under one trace (FR-07.39).

### 1.10 — Testing: MockLLMClient

```python
class MockLLMClient:
    """Deterministic LLM client for CI (FR-07.41–43)."""

    def __init__(self, responses: dict[ModelRole, str | dict] | None = None): ...

    async def generate(self, role, messages, params=None) -> LLMResponse:
        """Return pre-configured response. Exercises token counting and
        response parsing — only the HTTP call is replaced."""
        ...

    async def stream(self, role, messages, params=None) -> LLMResponse:
        """Same as generate() for mock — v1 buffer-then-stream means no
        difference in return type."""
        ...
```

Activated via `TTA_LLM_MOCK=true` in environment. The mock:
- Returns configurable responses per role
- Computes realistic token counts (using tiktoken or a fixed ratio)
- Exercises the full `LLMResponse` envelope construction
- Supports injecting errors for fallback testing: `mock.set_failure(role, tier, error)`

---

## 2. Pipeline Stage Contracts

### 2.1 — Stage Signature

Every stage is an async callable with the same signature:

```python
async def stage_name(state: TurnState, deps: PipelineDeps) -> TurnState:
    """
    Read fields from state, do work using deps, return updated state.
    TurnState is treated as immutable-ish: stages return a copy with
    updated fields rather than mutating in place.
    """
    ...
```

`PipelineDeps` bundles injected dependencies:

```python
@dataclass
class PipelineDeps:
    llm: LLMClient
    world: WorldService
    session_repo: SessionRepository
    turn_repo: TurnRepository
    safety_pre_input: SafetyHook
    safety_pre_gen: SafetyHook
    safety_post_gen: SafetyHook
    langfuse_trace: Trace | None
    settings: Settings
```

### 2.2 — Contract Summary

| Stage | Reads from TurnState | Writes to TurnState | External deps | Latency budget |
|-------|---------------------|---------------------|---------------|----------------|
| **Input Understanding** | `player_input`, `game_state` | `parsed_intent` | `LLMClient` (classification, maybe) | 300ms target, 1s max |
| **Context Assembly** | `parsed_intent`, `session_id`, `game_state` | `world_context`, `narrative_history` | `WorldService`, `SessionRepository` | 500ms target, 1s max |
| **Generation** | `parsed_intent`, `world_context`, `narrative_history`, `player_input`, `game_state` | `narrative_output`, `generation_prompt`, `model_used`, `token_count`, `world_state_updates` | `LLMClient` (generation + extraction) | ~13s max (remainder of 15s budget) |
| **Delivery** | `narrative_output`, `world_state_updates`, `session_id`, `turn_number` | `delivered`, `latency_ms` | SSE channel, `TurnRepository`, `WorldService` | 50ms target, 200ms max |

### 2.3 — TurnState Extensions

system.md §4.3 TurnState is normative. This plan adds optional fields (permitted
per §4.3 and §10):

```python
class TurnState(BaseModel):
    # --- Normative fields from system.md §4.3 --- (not repeated here)

    # --- Extensions for this component plan ---
    world_state_updates: list[WorldChange] | None = None  # Stage 3 output
    suggested_actions: list[str] | None = None             # Stage 3 output
    extraction_latency_ms: int | None = None               # Stage 3 metadata
    context_partial: bool = False                          # Stage 2 flag
    understanding_method: str | None = None                # "rules" or "llm"
```

```python
class WorldChange(BaseModel):
    """A single world-state mutation extracted from narrative."""
    change_type: str          # e.g. "item_taken", "door_opened", "npc_moved"
    entity_id: str            # Neo4j node ID
    field: str                # Property being changed
    old_value: str | None     # Previous value (if known)
    new_value: str            # New value
```

---

## 3. Input Understanding

### 3.1 — Rules-First Pattern Matching (system.md §6.6)

Before calling the LLM, a rule engine attempts fast classification:

| Pattern category | Regex / keyword patterns | Mapped intent |
|-----------------|-------------------------|---------------|
| **Movement** | `^(go\|walk\|move\|head\|travel)\s+(north\|south\|east\|west\|up\|down\|to\s+.+)` | `explore` |
| **Examination** | `^(look\|look at\|examine\|inspect\|read\|check)\s+(.+)` | `examine` |
| **Item use** | `^(use\|take\|pick up\|drop\|give\|open\|unlock)\s+(.+)` | `use_item` |
| **Speech** | `^(say\|tell\|ask\|talk to\|speak)\s+(.+)` or quoted text `"..."` / `'...'` | `speak` / `interact` |
| **Rest** | `^(wait\|rest\|sleep\|sit\|pause)` | `rest` |
| **Meta** | `^(help\|save\|load\|inventory\|quit\|menu\|what can i do)$` | meta command (short-circuit) |

Patterns are case-insensitive. If a rule matches, confidence is set to 0.9 and the
entity is extracted from the capture group. Entity resolution against world state
(matching extracted text to known items/NPCs/locations) is attempted via fuzzy
string matching against the `game_state` inventory and current location entities.

### 3.2 — LLM Fallback

If no rule matches (or confidence is low), the `classification` role is called:

- Model role: `classification`
- Temperature: 0.1
- Response format: structured JSON (`response_format: {"type": "json_object"}`)
- Max tokens: 256

Prompt template (reference — full template in `plans/prompts.md`):

```
Classify the player's input into a structured intent.

Current location: {location_name}
Nearby entities: {entity_list}
Recent conversation: {last_3_exchanges}

Player input: "{raw_input}"

Respond with JSON matching this schema:
{
  "intent": "explore|interact|use_item|examine|speak|rest|other",
  "entities": [{"name": "...", "type": "item|npc|object|location"}],
  "target": {"name": "...", "type": "..."} | null,
  "emotional_tone": "neutral|anxious|curious|frustrated|playful|distressed",
  "confidence": 0.0-1.0,
  "references": [{"pronoun": "...", "resolved_to": "..."}]
}
```

### 3.3 — ParsedIntent Schema

```python
class IntentType(str, Enum):
    EXPLORE = "explore"
    INTERACT = "interact"
    USE_ITEM = "use_item"
    EXAMINE = "examine"
    SPEAK = "speak"
    REST = "rest"
    OTHER = "other"

class EntityRef(BaseModel):
    name: str
    type: Literal["item", "npc", "object", "location"]
    resolved_id: str | None = None    # Neo4j node ID, if resolved

class AnaphoraRef(BaseModel):
    pronoun: str                       # "it", "them", "her"
    resolved_to: str                   # Resolved entity name

class ParsedIntent(BaseModel):
    intent: IntentType
    entities: list[EntityRef] = []
    target: EntityRef | None = None
    emotional_tone: str = "neutral"
    confidence: float = 0.8
    raw_input: str                     # Preserved original
    is_meta: bool = False
    references: list[AnaphoraRef] = []
```

### 3.4 — Edge Cases

| Input | Behavior |
|-------|----------|
| Empty / whitespace-only | Return `ParsedIntent(intent=OTHER, confidence=1.0, is_meta=False)`. Orchestrator generates a gentle prompt ("You pause, considering your options…") |
| Exceeds 2000 chars | Truncate to 2000 chars. Set `raw_input` to truncated text. Log a warning. |
| Emoji-only (e.g. "🔥🗡️") | No rule match → LLM fallback → likely `intent=other`, low confidence. Narrative handles it in-character. |
| Gibberish ("asdfghjkl") | No rule match → LLM fallback → `intent=other`, confidence < 0.5. Narrative responds in-character. |
| Multi-language | Process as-is. LLM handles mixed-language input. Response in session's configured language. |
| Meta command ("help") | `is_meta=True`. Pipeline short-circuits — no context assembly or generation. Return help text directly. |

### 3.5 — Failure Mode

If the classification LLM call fails (all retries exhausted), fall back to keyword
matching: scan input for known entity names and common verbs. If even that fails,
return `ParsedIntent(intent=OTHER, confidence=0.1, raw_input=input)`. The pipeline
proceeds — generation handles low-confidence input gracefully.

---

## 4. Context Assembly

### 4.1 — Data Sources

Context assembly makes **no LLM calls**. It fetches data from three sources:

| Source | Data retrieved | Interface |
|--------|---------------|-----------|
| **Neo4j** (via `WorldService`) | Current location, adjacent locations, NPCs at location, objects at location, relevant lore | `get_location_context(session_id, location_id, depth=1)` |
| **Postgres** (via `SessionRepository`) | Player inventory, character state, active quests | Part of `GameState` (already on `TurnState`) |
| **Postgres** (via `WorldService`) | Recent world events (last 5 turns) | `get_recent_events(session_id, limit=5)` |
| **Redis/Postgres** | Conversation history (last 10 exchanges) | `SessionRepository.get_history(session_id, limit=10)` |

Queries to Neo4j and conversation history can run **in parallel** since they're
independent:

```python
location_ctx, recent_events, history = await asyncio.gather(
    deps.world.get_location_context(state.session_id, current_location_id),
    deps.world.get_recent_events(state.session_id, limit=5),
    deps.session_repo.get_history(state.session_id, limit=10),
)
```

### 4.2 — Relevance Tiering (FR-08.15)

Context elements are tagged with relevance tiers for token budget truncation:

| Tier | Priority | Content | Example |
|------|----------|---------|---------|
| **Directly referenced** | 1 (highest) | Entities named in input or resolved via anaphora | Player said "open the door" → door details |
| **Scene-present** | 2 | NPCs and objects at current location | NPCs in the room |
| **Recently active** | 3 | Entities involved in last 2-3 turns | NPC the player spoke to last turn |
| **Narratively adjacent** | 4 | Connected lore, active quests | Quest objective mentioning this location |
| **Background** | 5 (lowest) | Time of day, weather, ambient conditions | "It is evening." |

The `parsed_intent.entities` and `parsed_intent.target` fields drive tier-1 tagging.
Tier 2-5 are structural (based on graph relationships and recency).

### 4.3 — Token Budget Allocation

Token budget is computed per-call based on the target model's context window:

```
available = context_window - output_reservation - system_prompt_tokens
```

Distribution of `available` tokens across priority tiers:

| S07 Priority | Content | Budget share | Truncation order |
|-------------|---------|-------------|-----------------|
| **P0** | System prompt + safety guardrails + format instructions | Reserved first (never truncated) | Never |
| **P1** | Current turn input + last 3 exchanges | ~20% of remaining | Last |
| **P2** | World context (location, NPCs, items, events) | ~40% of remaining | Middle |
| **P3** | Extended conversation history (exchanges 4-10), background lore | ~40% of remaining | First |

Token counting uses **tiktoken** with the `cl100k_base` encoding as a conservative
approximation. Over-counting by up to 10% is acceptable (FR-07.14).

When history is truncated, dropped messages are replaced with a summary line:
`"[Earlier: player explored the cave and found a rusty key]"` (FR-07.15). The
summary is generated by the `summarization` role if the dropped content exceeds
500 tokens; otherwise a simple concatenation of turn intents is used.

### 4.4 — WorldContext Schema

```python
class WorldContext(BaseModel):
    """Assembled context for generation (S08 §5.3)."""
    location: LocationDetail
    inventory: list[ItemDetail]
    nearby_npcs: list[NPCDetail]
    nearby_objects: list[ObjectDetail]
    recent_events: list[WorldEventSummary]
    conversation_history: list[HistoryEntry]
    active_quests: list[QuestSummary]
    world_time: str | None = None          # "evening", "dawn", etc.
    character_state: str | None = None     # "tired", "wounded", etc.
    genre_context: str | None = None       # "dark fantasy", "cozy mystery"
    is_partial: bool = False               # True if queries timed out
    relevance_tags: dict[str, int] = {}    # entity_id → tier (1-5)

class LocationDetail(BaseModel):
    id: str
    name: str
    description: str
    exits: list[ExitDetail]
    atmosphere: str | None = None

class NPCDetail(BaseModel):
    id: str
    name: str
    description: str
    disposition: str
    relationship_to_player: str | None = None
```

### 4.5 — Performance

- **Neo4j query target**: <100ms p95 (system.md §5.1). Queries use parameterized
  Cypher with index lookups on `Location.id`, `NPC.id`, `Item.id`.
- **Total stage target**: <500ms p95. If any query exceeds its budget, the stage
  proceeds with whatever data is available, sets `is_partial=True`, and logs a
  performance warning.
- **Failure mode**: if Neo4j is entirely down, assemble context from `GameState`
  (already cached in `TurnState`) plus conversation history only. Set
  `is_partial=True`. The narrative will be less grounded but playable.

---

## 5. Generation

### 5.1 — System Prompt Structure

The generation prompt is assembled from template variables. The ordering within the
prompt is:

```
┌─────────────────────────────────────────┐
│ 1. System prompt (role, rules, format)  │  ← P0: never truncated
├─────────────────────────────────────────┤
│ 2. World context block                  │  ← P2: truncated middle
│    - Location, NPCs, items, exits       │
│    - Active quests, character state      │
│    - Recent events                      │
├─────────────────────────────────────────┤
│ 3. Conversation history                 │  ← P3 (older) / P1 (recent 3)
│    - [Summary of older turns]           │
│    - Full text of last 3 exchanges      │
├─────────────────────────────────────────┤
│ 4. Current turn input                   │  ← P1: truncated last
│    - Player's raw input                 │
│    - Parsed intent + entities           │
└─────────────────────────────────────────┘
```

Prompt template details are defined in `plans/prompts.md`. This plan defines the
interface:

```python
def build_generation_prompt(
    intent: ParsedIntent,
    context: WorldContext,
    history: list[HistoryEntry],
    template: PromptTemplate,
    token_budget: int,
) -> list[Message]:
    """Assemble the generation prompt within token budget."""
    ...
```

### 5.2 — Buffer-Then-Stream Execution

Generation calls the LLM with `stream=True` internally (for incremental collection
and timeout behavior), but buffers the complete response before returning:

```python
async def run_generation(state: TurnState, deps: PipelineDeps) -> TurnState:
    messages = build_generation_prompt(...)

    # 1. Call LLM — internally streams but returns complete response
    response = await deps.llm.stream(
        role=ModelRole.GENERATION,
        messages=messages,
        params=template_params,
    )

    # 2. Post-generation safety hook (pass-through in v1)
    safety_result = await deps.safety_post_gen.check(
        response.text, TurnContext(state)
    )
    if safety_result.action == "block":
        # Retry once with same context
        response = await deps.llm.stream(...)

    # 3. Quality checks (FR-08.22)
    if not passes_quality_checks(response.text):
        response = await deps.llm.stream(...)  # Retry with different seed

    # 4. World change extraction (runs inline — see §5.4)
    changes = await extract_world_changes(response.text, state, deps)

    return state.model_copy(update={
        "narrative_output": response.text,
        "model_used": response.model_used,
        "token_count": response.token_count,
        "generation_prompt": serialize_messages(messages),
        "world_state_updates": changes,
    })
```

### 5.3 — Quality Checks (FR-08.22)

```python
def passes_quality_checks(text: str) -> bool:
    """Reject obviously bad generation output."""
    if not text or len(text.strip()) < 20:
        return False   # Too short
    if has_excessive_repetition(text, threshold=3, min_length=50):
        return False   # Repeated phrases
    if breaks_fourth_wall(text):
        return False   # "As an AI..." detection
    return True
```

On quality failure: retry once with the same prompt (different random seed via a
slight temperature bump: +0.05). If both attempts fail, deliver the better of the
two (longer, less repetitive) with a quality warning logged.

### 5.4 — World Change Extraction

After narrative generation, a separate LLM call extracts world-state changes:

- Model role: `extraction`
- Prompt: "Given this narrative, identify world-state changes as structured JSON."
- Schema: `list[WorldChange]`

**Ordering and latency**: extraction runs **after** the narrative buffer is complete
but **before** the delivery stage begins. This adds latency between generation
completion and first SSE token. Expected extraction time: 1-3s.

If extraction fails (LLM error or malformed JSON), the turn proceeds with
`world_state_updates = []` — no state changes are applied. A warning is logged. This
is safe because no state mutation occurs, and the next turn's context will reflect
the unchanged world.

**Validation**: each `WorldChange` is validated against world-state constraints
before application:
- Does the entity exist in the current session's world graph?
- Is the change consistent with game rules (e.g., can't open a locked door without
  the key)?

If a change fails validation, it is rejected (not applied) and logged. If the
rejection was due to a hard constraint, the generation stage retries once with a
constraint reminder injected into the prompt (FR-08.20).

### 5.5 — Model Selection

| Task | Model role | Rationale |
|------|-----------|-----------|
| Narrative prose | `generation` | Quality matters. Creative temperature. |
| World change extraction | `extraction` | Structured output. Fast model is fine. |
| Quality-check retry | `generation` | Same role, slight temperature bump. |

---

## 6. Delivery

### 6.1 — SSE Event Sequence

The delivery stage streams the buffered narrative to the client and finalizes state:

```
1. emit turn_start  {turn_number, timestamp}
2. emit thinking    {}                              ← sent before generation
3. [generation runs — client sees thinking indicator]
4. [generation + extraction complete]
5. emit narrative_token {token: "The "}             ← from buffer
6. emit narrative_token {token: "forest "}
7. emit narrative_token {token: "stirs..."}
8. ...
9. emit world_update  {changes: [...]}              ← extracted changes
10. emit turn_complete {turn_number, model_used, latency_ms, suggested_actions}
```

Note: `turn_start` and `thinking` are emitted by the **orchestrator** before
generation begins (see §7.2). The delivery stage handles steps 5-10.

### 6.2 — Token Streaming from Buffer

The buffer (a string) is split into word-boundary tokens:

```python
async def stream_narrative_tokens(
    narrative: str,
    sse_channel: SSEChannel,
    word_delay_ms: int = 30,
) -> None:
    """Stream narrative text as word-boundary tokens."""
    words = narrative.split()
    for i, word in enumerate(words):
        token = word + (" " if i < len(words) - 1 else "")
        await sse_channel.send("narrative_token", {"token": token})
        await asyncio.sleep(word_delay_ms / 1000)  # Simulate typing cadence
```

The `word_delay_ms` creates a natural reading pace. It's configurable (default 30ms)
and can be set to 0 in tests.

### 6.3 — Error Event Formatting

If the pipeline fails at any stage, the delivery layer sends:

```
event: error
data: {"code": "generation_failed", "message": "The story pauses momentarily..."}
```

Error codes:

| Code | Trigger | Player-facing message |
|------|---------|----------------------|
| `generation_failed` | All LLM tiers exhausted | "The story pauses momentarily…" |
| `rate_limited` | Per-session turn rate limit hit | "You're moving too quickly. Take a breath." |
| `session_expired` | Session TTL exceeded | "Your story fades into memory…" |
| `internal_error` | Unexpected exception | "Something unexpected happened. Please try again." |

Players never see stack traces, model names, or technical details.

### 6.4 — Turn Record Finalization

After streaming completes:

1. **Update turn record** in Postgres:
   ```sql
   UPDATE turns SET
     status = 'complete',
     narrative_output = $1,
     parsed_intent = $2,
     world_context = $3,
     model_used = $4,
     latency_ms = $5,
     token_count = $6,
     completed_at = now()
   WHERE id = $7
   ```

2. **Apply world-state changes** to Neo4j (atomically, in a single transaction):
   ```python
   await deps.world.apply_world_changes(state.session_id, state.world_state_updates)
   ```

3. **Record world events** in Postgres:
   ```sql
   INSERT INTO world_events (session_id, turn_id, event_type, entity_id, payload)
   VALUES ($1, $2, $3, $4, $5)
   ```

4. **Update Redis session cache** with new game state (location, inventory changes).

**Transaction boundary**: steps 1-3 run in a single Postgres transaction. The Neo4j
write (step 2) is a separate transaction. If the Neo4j write fails, the turn record
is still updated (status='complete') but world_events are not recorded and Neo4j
state is stale. A background reconciliation check can detect and fix this (logged as
critical). This is acceptable for v1.

**Happens-before guarantee** (EC-08.10): the pipeline orchestrator ensures turn N's
state changes are fully committed (steps 1-3 complete) before turn N+1's context
assembly begins. The Postgres concurrent-turn lock (§0.3) enforces this — a new turn
can't start while the previous is `processing`.

---

## 7. Pipeline Orchestrator

### 7.1 — Wiring

The orchestrator is a plain async function. No frameworks.

```python
async def process_turn(
    state: TurnState,
    deps: PipelineDeps,
    sse_channel: SSEChannel,
) -> TurnState:
    """Execute the 4-stage turn pipeline."""
    trace = deps.langfuse_trace

    # Emit early SSE events
    await sse_channel.send("turn_start", {
        "turn_number": state.turn_number,
        "timestamp": utcnow_iso(),
    })
    await sse_channel.send("thinking", {})

    # Schedule still_thinking after 3s
    still_thinking_task = asyncio.create_task(
        _send_still_thinking(sse_channel, delay=3.0)
    )

    try:
        # Stage 1: Input Understanding
        with trace_span(trace, "understanding"):
            state = await input_understanding(state, deps)

        # Meta-command short circuit
        if state.parsed_intent and state.parsed_intent.is_meta:
            return await handle_meta_command(state, deps, sse_channel)

        # Pre-input safety hook (pass-through in v1)
        await deps.safety_pre_input.check(state.player_input, TurnContext(state))

        # Stage 2: Context Assembly
        with trace_span(trace, "context_assembly"):
            state = await context_assembly(state, deps)

        # Pre-generation safety hook (pass-through in v1)
        await deps.safety_pre_gen.check(
            state.generation_prompt or "", TurnContext(state)
        )

        # Stage 3: Generation (includes post-gen safety + extraction)
        with trace_span(trace, "generation"):
            state = await generation(state, deps)

        # Cancel still_thinking if not yet fired
        still_thinking_task.cancel()

        # Stage 4: Delivery
        with trace_span(trace, "delivery"):
            state = await delivery(state, deps, sse_channel)

    except AllTiersFailedError:
        still_thinking_task.cancel()
        await sse_channel.send("error", {
            "code": "generation_failed",
            "message": "The story pauses momentarily…",
        })
        await deps.turn_repo.update_status(state.turn_id, "failed")
        # Preserve player input for retry (already in turns table)
        raise

    except Exception as exc:
        still_thinking_task.cancel()
        structlog.get_logger().error("pipeline_error", error=str(exc))
        await sse_channel.send("error", {
            "code": "internal_error",
            "message": "Something unexpected happened. Please try again.",
        })
        await deps.turn_repo.update_status(state.turn_id, "failed")
        raise

    return state
```

### 7.2 — Stage Error Isolation

Each stage handles its own failures. The orchestrator does NOT retry the full
pipeline (FR-08.41):

| Stage failure | Orchestrator behavior |
|---------------|----------------------|
| Understanding fails | Proceeds with `ParsedIntent(intent=OTHER, confidence=0.1)` |
| Context assembly fails | Proceeds with `WorldContext(is_partial=True)` + minimal context |
| Generation fails (all tiers) | Raises `AllTiersFailedError` → "story pauses" |
| Delivery fails (SSE error) | Turn is still finalized in DB. Player missed the stream. |
| Delivery fails (persistence) | Log critical. Turn text was delivered but state not saved. |

### 7.3 — Concurrency Model

One turn at a time per session, enforced via Postgres (system.md §4.1):

```python
async def acquire_turn_lock(session_id: str, turn_request: TurnRequest) -> Turn:
    """Create turn row with concurrent-turn guard.
    Raises TurnInProgressError (→ 409) if another turn is processing."""
    async with db.begin() as tx:
        existing = await tx.execute(
            text("""
                SELECT id FROM turns
                WHERE session_id = :sid AND status = 'processing'
                FOR UPDATE
            """),
            {"sid": session_id},
        )
        if existing.first():
            raise TurnInProgressError(session_id)

        # Check idempotency
        if turn_request.idempotency_key:
            dup = await tx.execute(
                text("""
                    SELECT id FROM turns
                    WHERE session_id = :sid AND idempotency_key = :key
                """),
                {"sid": session_id, "key": turn_request.idempotency_key},
            )
            if row := dup.first():
                return Turn(id=row.id, already_exists=True)

        # Assign turn number
        max_num = await tx.execute(
            text("SELECT COALESCE(MAX(turn_number), 0) FROM turns WHERE session_id = :sid"),
            {"sid": session_id},
        )
        next_number = max_num.scalar() + 1

        # Insert turn row
        turn = await tx.execute(
            text("""
                INSERT INTO turns (id, session_id, turn_number, idempotency_key, status, player_input)
                VALUES (:id, :sid, :num, :key, 'processing', :input)
                RETURNING id
            """),
            {"id": new_uuid(), "sid": session_id, "num": next_number,
             "key": turn_request.idempotency_key, "input": turn_request.input},
        )
        return Turn(id=turn.scalar(), turn_number=next_number)
```

### 7.4 — Cost Accumulation and Caps

Per-session cost tracking:

```python
async def check_session_cost(session_id: str, new_cost: float, deps: PipelineDeps) -> None:
    """Check session cost against caps (FR-07.20)."""
    session = await deps.session_repo.get(session_id)
    total_cost = session.total_cost_usd + new_cost

    cap = deps.settings.session_cost_cap_usd  # Default: e.g. $1.00
    if total_cost >= cap:
        raise BudgetExceededError(f"Session cost ${total_cost:.4f} exceeds cap ${cap:.2f}")
    if total_cost >= cap * 0.8:
        structlog.get_logger().warning(
            "session_cost_approaching_cap",
            session_id=session_id,
            total_cost=total_cost,
            cap=cap,
        )
```

The cost check runs after generation completes (cost is known) but before delivery.
At 100%, the turn is rejected with a graceful session-ending message. At 80%, a
warning is logged (operators can configure alerts).

### 7.5 — Langfuse Tracing

One trace per turn, child spans per stage (FR-08.42):

```python
trace = langfuse.trace(
    name="turn",
    metadata={
        "session_id": state.session_id,
        "turn_number": state.turn_number,
    },
)
```

Each stage is wrapped in a span:

```python
@contextmanager
def trace_span(trace: Trace | None, name: str):
    if trace:
        span = trace.span(name=name)
        start = time.monotonic()
        try:
            yield span
        finally:
            span.end(metadata={"duration_ms": int((time.monotonic() - start) * 1000)})
    else:
        yield None
```

LLM calls within the generation span are recorded as Langfuse **generation** events
(§1.9), linked as children of the generation span.

---

## 8. Testing Strategy

### 8.1 — Unit Tests

Each stage tested in isolation with mocked dependencies:

| Stage | Mock strategy | Key assertions |
|-------|--------------|----------------|
| Input Understanding | Mock `LLMClient.generate()` for classification | Correct intent for known patterns; LLM fallback triggers on unknown input; ParsedIntent schema valid |
| Context Assembly | Mock `WorldService`, `SessionRepository` | Correct field population; relevance tagging; token budget respected; partial context on timeout |
| Generation | Mock `LLMClient.stream()` | Prompt structure correct; quality checks trigger retry; world changes extracted; safety hooks called |
| Delivery | Mock `SSEChannel`, `TurnRepository`, `WorldService` | Correct event sequence; turn record updated; world events recorded |

```python
# Example: test rules-first intent matching
def test_movement_intent_parsed_by_rules():
    state = make_turn_state(player_input="go north")
    result = await input_understanding(state, mock_deps)

    assert result.parsed_intent.intent == IntentType.EXPLORE
    assert result.parsed_intent.confidence >= 0.9
    assert result.understanding_method == "rules"
```

### 8.2 — Unit Tests: LLM Client

| Test case | Setup | Assertion |
|-----------|-------|-----------|
| Successful generation | Mock LiteLLM returns text | `LLMResponse` has all fields |
| Transient error → retry | Mock raises `RateLimitError` then succeeds | 2 calls made, success returned |
| All retries fail → fallback | Primary always times out | Fallback model used, `tier_used="fallback"` |
| All tiers fail | Both models always fail | `AllTiersFailedError` raised |
| Malformed JSON → retry | First response is invalid JSON | Retried, second attempt parsed |
| Configuration error → no retry | Mock raises `AuthenticationError` | Fails immediately, 1 call made |
| Circuit breaker cooldown | 5 failures in 60s | Model skipped, fallback used directly |
| Cost computation | Known token counts | `cost_usd` matches pricing table |
| Smaller fallback context | Fallback model has smaller window | Context re-truncated before call |

### 8.3 — Integration Tests

Full pipeline with `MockLLMClient`, real Postgres + Neo4j + Redis (via Docker Compose
in CI):

```python
@pytest.mark.integration
async def test_full_turn_pipeline(
    db_session, neo4j_session, redis_client, mock_llm
):
    """Submit a turn and verify end-to-end flow."""
    # Arrange: seed world, create session
    session = await create_test_session(db_session, neo4j_session)

    # Act: process turn
    state = make_turn_state(
        session_id=session.id,
        player_input="look behind the waterfall",
    )
    result = await process_turn(state, make_deps(mock_llm, db_session, ...))

    # Assert: full pipeline completed
    assert result.delivered is True
    assert result.narrative_output is not None
    assert result.parsed_intent.intent == IntentType.EXAMINE

    # Assert: turn persisted
    turn = await db_session.get(Turn, result.turn_id)
    assert turn.status == "complete"
    assert turn.narrative_output == result.narrative_output
```

### 8.4 — BDD Test Mapping

S08 Gherkin scenarios map to pytest-bdd step definitions:

| Gherkin scenario | Feature file | Test file |
|------------------|-------------|-----------|
| AC-08.1: End-to-end turn processing | `features/turn_pipeline.feature` | `step_defs/test_turn_pipeline.py` |
| AC-08.2: Input understanding (5 scenarios) | `features/input_understanding.feature` | `step_defs/test_input_understanding.py` |
| AC-08.3: Context assembly (3 scenarios) | `features/context_assembly.feature` | `step_defs/test_context_assembly.py` |
| AC-08.4: Generation quality (4 scenarios) | `features/generation.feature` | `step_defs/test_generation.py` |
| AC-08.5: Delivery (4 scenarios) | `features/delivery.feature` | `step_defs/test_delivery.py` |
| AC-08.6: Error resilience (4 scenarios) | `features/error_resilience.feature` | `step_defs/test_error_resilience.py` |
| AC-08.7: Observability (2 scenarios) | `features/observability.feature` | `step_defs/test_observability.py` |

### 8.5 — High-Risk Scenario Tests

These test the failure modes most likely to cause production incidents:

| Scenario | Type | What it validates |
|----------|------|-------------------|
| Primary model timeout → fallback succeeds | Unit (LLM client) | Fallback chain works; tier recorded |
| All tiers fail → "story pauses" | Integration | Graceful failure message; turn marked `failed`; input preserved |
| Malformed JSON from extraction → no state update | Unit (generation) | Turn completes without state changes |
| Duplicate idempotency key → original returned | Integration | No reprocessing; same turn_id returned |
| Concurrent turn → 409 Conflict | Integration | Second submission rejected; first completes |
| Client disconnects mid-stream | Integration | Turn still finalized in DB as `complete` |
| Neo4j down → partial context generation | Integration | Narrative generated with minimal context |
| World-state conflict → retry with constraint | Unit (generation) | Conflicting change rejected; generation retried |
| Session cost at 80% → warning logged | Unit (orchestrator) | Warning emitted; turn still proceeds |
| Session cost at 100% → graceful stop | Unit (orchestrator) | `BudgetExceededError`; session-ending message |

### 8.6 — Performance Tests

Latency budget verification under realistic conditions:

```python
@pytest.mark.performance
async def test_turn_latency_budget(mock_llm_with_delay):
    """Verify each stage stays within its latency budget."""
    mock_llm_with_delay.set_delay(ModelRole.CLASSIFICATION, 0.2)
    mock_llm_with_delay.set_delay(ModelRole.GENERATION, 2.0)
    mock_llm_with_delay.set_delay(ModelRole.EXTRACTION, 1.0)

    state = make_turn_state(player_input="I look behind the waterfall")
    result = await process_turn(state, deps)

    assert result.stage_latencies["understanding"] < 1000   # < 1s max
    assert result.stage_latencies["context_assembly"] < 1000 # < 1s max
    assert result.latency_ms < 15_000                        # < 15s total p95
```

For load testing, a locust script simulates concurrent sessions submitting turns and
verifies that p95 latency stays within budget under 100 concurrent sessions
(system.md §5.1).

---

## Appendix A — Dependency Summary

| External dependency | Used by | Failure mode |
|--------------------|---------|-------------|
| LiteLLM | `LiteLLMClient` | Retry + fallback chain |
| tenacity | `LiteLLMClient` retry | — (library) |
| tiktoken | Token counting in context assembly | Fallback to char/4 estimate |
| Langfuse SDK | Tracing in orchestrator + LLM client | Skip tracing, continue serving |
| Neo4j driver | `WorldService` (context assembly, state changes) | Partial context fallback |
| asyncpg (via SQLModel) | Turn persistence, session queries | 503 if down |
| Redis (aioredis) | Session cache, SSE pub/sub | Operate without cache |
| structlog | All modules | — (logging library) |

## Appendix B — Configuration Reference

All settings via environment variables (loaded by `Settings` in system.md §7.4):

| Variable | Default | Description |
|----------|---------|-------------|
| `TTA_LLM_PRIMARY_MODEL` | `claude-sonnet-4-20250514` | Primary generation model |
| `TTA_LLM_FALLBACK_MODEL` | `claude-haiku-4-20250514` | Fallback generation model |
| `TTA_LLM_CLASSIFICATION_MODEL` | `claude-haiku-4-20250514` | Classification/extraction model |
| `TTA_LLM_API_KEY` | (required) | LLM provider API key |
| `TTA_LLM_MOCK` | `false` | Enable mock LLM client for testing |
| `TTA_LLM_GENERATION_TIMEOUT` | `10` | Generation call timeout (seconds) |
| `TTA_LLM_CLASSIFICATION_TIMEOUT` | `5` | Classification call timeout (seconds) |
| `TTA_LLM_CIRCUIT_THRESHOLD` | `5` | Failures before cooldown |
| `TTA_LLM_CIRCUIT_WINDOW` | `60` | Circuit breaker window (seconds) |
| `TTA_LLM_CIRCUIT_COOLDOWN` | `30` | Cooldown period (seconds) |
| `TTA_SESSION_COST_CAP_USD` | `1.00` | Max LLM cost per session |
| `TTA_TURN_RATE_LIMIT` | `10` | Max turns per minute per session |
| `TTA_MAX_INPUT_LENGTH` | `2000` | Max player input characters |
| `TTA_SSE_WORD_DELAY_MS` | `30` | Delay between SSE word tokens |
| `TTA_CONTEXT_HISTORY_LIMIT` | `10` | Conversation exchanges to retrieve |
| `TTA_CONTEXT_EVENTS_LIMIT` | `5` | Recent world events to retrieve |

---

## Changelog

| Date | Author | Description |
|------|--------|-------------|
| 2025-07-21 | Copilot audit | Corrected normative code examples to match actual implementation. Updated field names, types, enum members, file paths, and model definitions to reflect codebase as of commit 8045faa. |
