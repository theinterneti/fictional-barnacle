# S07 — LLM Integration

> **Status**: 📝 Draft
> **Level**: 2 — AI & Content
> **Dependencies**: S01 (Core Game Loop), S03 (Narrative Engine)
> **Last Updated**: 2026-04-07

## 1 — Purpose

This spec defines how TTA interfaces with large language models. It is a **technical enabler** — every spec that involves AI generation (S08, S09, S19) depends on the behaviors described here.

TTA treats LLMs as **unreliable, expensive, interchangeable utilities**. The system must work across providers, degrade gracefully when models fail, and give operators visibility into cost and quality. No game logic should depend on a specific model or provider.

### Design values applied

| Value | Implication |
|---|---|
| **Fun** | Generation latency must stay low enough to maintain immersion. Streaming helps. |
| **Coherence** | Context window management must preserve the information that keeps the story consistent. |
| **Craftsmanship** | Model routing, fallback, and observability must be production-grade, not hacked together. |
| **Openness** | LiteLLM abstraction means any OpenAI-compatible provider works — local Ollama to cloud APIs. |

---

## 2 — User Stories

### US-07.1 — Player experiences consistent quality
> As a **player**, I want narrative quality to remain playable even when the primary AI model is unavailable, so that my game session is never interrupted by infrastructure problems.

### US-07.2 — Operator controls costs
> As an **operator**, I want to see per-session and per-turn LLM cost breakdowns and set spending caps, so that a popular game doesn't produce surprise bills.

### US-07.3 — Operator switches models without code changes
> As an **operator**, I want to change which model handles narrative generation via configuration — not a code deploy — so that I can respond to pricing changes or model deprecations quickly.

### US-07.4 — Developer tests without live LLM calls
> As a **developer**, I want deterministic test modes that don't call real LLMs, so that CI is fast, free, and reproducible.

### US-07.5 — Developer traces a slow turn
> As a **developer**, I want every LLM call to be traced in Langfuse with prompt, completion, latency, token count, and model used, so that I can debug quality and performance issues.

### US-07.6 — Player sees text appear progressively
> As a **player**, I want the narrative response to stream word-by-word into my interface rather than appearing as a block after a long wait, so that the experience feels responsive.

### US-07.7 — Author tunes generation style per task
> As a **content author**, I want to specify temperature, top-p, and max tokens per prompt template, so that classification tasks are deterministic and narrative tasks are creative.

---

## 3 — Model Abstraction Layer

### 3.1 — Unified interface

All LLM calls in TTA pass through a single abstraction. This abstraction:

- Accepts a **model role** (e.g. `generation`, `classification`, `extraction`), not a model name.
- Resolves the role to a concrete model via configuration.
- Returns a **uniform response envelope** regardless of provider.
- Handles retries, fallback, and timeout internally — callers do not implement retry logic.

> **Implementation note (non-normative):** LiteLLM's unified `completion()` interface and Router support streaming (`stream=True`), automatic fallback chains, and built-in cost tracking — all requirements of this spec. The spec does not mandate LiteLLM; any library that satisfies these behaviors is acceptable.

**FR-07.01**: The system SHALL provide a single callable interface for all LLM interactions. Callers specify a model role, messages, and generation parameters. The interface resolves the role to a provider/model pair.

**FR-07.02**: The response envelope SHALL include: completion text, token counts (prompt + completion), model actually used, latency in milliseconds, and a trace ID linking to the observability backend.

**FR-07.03**: Callers SHALL NOT reference provider-specific model names (e.g. `gpt-4o`, `claude-sonnet-4-20250514`). They reference roles. Role-to-model mapping is configuration.

### 3.2 — Model roles

TTA defines these model roles. Each role has different quality, cost, and latency requirements:

| Role | Purpose | Typical characteristics |
|---|---|---|
| `generation` | Narrative prose output | High quality, higher latency acceptable, creative temperature |
| `classification` | Intent detection, emotion tagging | Fast, cheap, deterministic, structured output |
| `extraction` | Entity extraction, world-state parsing | Moderate quality, structured output required |
| `summarization` | Compressing conversation history | Moderate quality, large context window preferred |

**FR-07.04**: Each model role SHALL be independently configurable with: primary model, fallback model(s), temperature, max output tokens, and timeout.

**FR-07.05**: The system SHALL support adding new model roles via configuration without code changes.

---

## 4 — Fallback Tiers

TTA uses a **2–3 tier** fallback strategy. This replaces the old 9-tier cascade, which was overengineered and hard to reason about.

### 4.1 — Tier structure

| Tier | Example | When used | Behavioral contract |
|---|---|---|---|
| **Primary** | Best-available model for the role | Default, first attempt | Full quality. No degradation. |
| **Fallback** | Cheaper or more available model | Primary fails or times out | Acceptable quality. Player may notice slight degradation. Game remains coherent. |
| **Last-resort** | Smallest viable model or cached response | Fallback also fails | Playable but degraded. System prioritizes keeping the session alive over quality. |

**FR-07.06**: On primary model failure (timeout, rate limit, 5xx, malformed response), the system SHALL automatically retry on the fallback model without player-visible interruption.

**FR-07.07**: On fallback failure, the system SHALL attempt the last-resort tier. If last-resort also fails, the system SHALL return a graceful error to the player (e.g. "The story pauses for a moment…") and log a critical alert.

**FR-07.08**: Each fallback attempt SHALL be a fresh request with the same prompt — not a retry of the failed request to the same endpoint.

**FR-07.09**: The system SHALL record which tier was used for every LLM call. Operators can alert when fallback usage exceeds a configurable threshold (e.g. >10% of calls in a 5-minute window).

### 4.2 — Fallback triggers

A model call is considered failed when any of these occur:

| Trigger | Detection | Behavior |
|---|---|---|
| **Timeout** | No first token within per-role timeout (default: 10s for generation, 5s for classification) | Move to next tier |
| **HTTP error** | 429 (rate limit), 500, 502, 503 from provider | Move to next tier |
| **Empty response** | Model returns empty string or only whitespace | Move to next tier |
| **Malformed structured output** | JSON parse fails when structured output was requested | Retry once on same tier, then move to next |
| **Content filter** | Provider's safety filter blocks the response | Log and retry with modified prompt on same tier, then move to next |

**FR-07.10**: Timeout values SHALL be configurable per model role.

**FR-07.11**: The system SHALL implement circuit-breaking: if a model accumulates N failures within M seconds (configurable), skip it entirely for a cooldown period rather than attempting it on every call.

### 4.3 — What fallback does NOT do

- Fallback does NOT change the prompt. The same prompt goes to each tier.
- Fallback does NOT retry infinitely. Maximum 1 attempt per tier, maximum 3 tiers.
- Fallback does NOT hide the degradation from observability. Every tier transition is logged.

---

## 5 — Context Window Management

### 5.1 — The problem

LLMs have finite context windows. A long-running TTA session can accumulate conversation history, world state, NPC details, and system prompts that exceed any model's window. The system must stay within limits without losing critical context.

### 5.2 — Context budget allocation

Each LLM call's context window is divided into priority tiers:

| Priority | Content | Budget share | Truncation behavior |
|---|---|---|---|
| **P0 — Never truncate** | System prompt, safety guardrails, output format instructions | Fixed allocation (reserved first) | Never removed. If system prompt alone exceeds the window, that's a configuration error. |
| **P1 — Truncate last** | Current turn input, most recent 2-3 conversation exchanges | ~20% of remaining budget | Summarize rather than drop. Last resort: truncate oldest of the recent exchanges. |
| **P2 — Truncate middle** | World state context, NPC details, location descriptions | ~40% of remaining budget | Prioritize by relevance to current scene. Drop distant/irrelevant context first. |
| **P3 — Truncate first** | Extended conversation history, background lore | Remainder | Summarize aggressively or drop entirely. |

**FR-07.12**: Before every LLM call, the system SHALL compute the total token count of the assembled prompt and verify it fits within the target model's context window minus the reserved output token budget.

**FR-07.13**: If the assembled prompt exceeds the context budget, the system SHALL truncate according to the priority tiers above — removing P3 content first, then P2, never P0.

**FR-07.14**: Token counting SHALL use a tokenizer compatible with the target model (or a conservative approximation). Over-counting by up to 10% is acceptable; under-counting is not.

**FR-07.15**: When conversation history is truncated, the system SHALL replace dropped messages with a brief summary (e.g. "[Earlier: player explored the cave and found a key]") rather than silently dropping them.

### 5.3 — Output token reservation

**FR-07.16**: The system SHALL reserve a configurable number of tokens for the model's output (default: 1024 for generation, 256 for classification/extraction). The input context must fit within `context_window - output_reservation`.

---

## 6 — Token Budgeting and Cost Management

### 6.1 — Per-turn cost tracking

**FR-07.17**: The system SHALL record the cost of every LLM call, computed from token counts and the model's configured per-token pricing.

**FR-07.18**: Per-turn cost SHALL be the sum of all LLM calls made during that turn (which may include classification + context assembly + generation).

**FR-07.19**: Per-session cost SHALL be the running sum of all per-turn costs.

### 6.2 — Cost controls

**FR-07.20**: The system SHALL support a configurable **per-session cost cap**. When a session approaches the cap (configurable threshold, default 80%), the system SHALL:
1. Log a warning.
2. Optionally downgrade to cheaper models for remaining turns.
3. At 100%, refuse further LLM calls and return a graceful session-ending message.

**FR-07.21**: The system SHALL support a configurable **per-turn cost cap**. If a single turn would exceed this cap (e.g. due to very long context), the system SHALL aggressively truncate context to reduce input tokens rather than refusing the turn.

### 6.3 — Cost reporting

**FR-07.22**: The system SHALL expose cost metrics (per-turn, per-session, per-model, per-role) to the observability backend for dashboarding and alerting.

---

## 7 — Streaming

### 7.1 — Token-by-token delivery

**FR-07.23**: For `generation` role calls, the system SHALL request streaming responses from the LLM provider and forward tokens to the player via SSE as they arrive.

**FR-07.24**: The SSE stream SHALL emit events in this format:
```
event: token
data: {"text": "The ", "turn_id": "t-abc123"}

event: token
data: {"text": "forest ", "turn_id": "t-abc123"}

event: done
data: {"turn_id": "t-abc123", "total_tokens": 847}
```

**FR-07.25**: If streaming is interrupted mid-generation (client disconnect, model error), the system SHALL:
1. Record the partial response in the session history.
2. Mark the turn as `partial` in the data store.
3. On the player's next turn, acknowledge the interruption naturally (e.g. the narrative picks up where it left off).

### 7.2 — Non-streaming calls

**FR-07.26**: For `classification`, `extraction`, and `summarization` roles, the system SHALL use non-streaming calls by default (structured output is easier to parse from complete responses).

**FR-07.27**: Non-streaming calls SHALL still respect the same timeout and fallback behavior as streaming calls.

---

## 8 — Structured Output

### 8.1 — When to use structured output

Some pipeline stages need structured data from the LLM, not free-form text. Examples:
- Intent classification: `{"intent": "explore", "confidence": 0.9}`
- Entity extraction: `{"entities": [{"name": "Old Key", "type": "item"}]}`
- Emotion tagging: `{"primary_emotion": "curiosity", "intensity": 0.7}`

**FR-07.28**: The system SHALL support requesting structured (JSON) output from LLMs via the provider's native structured output mode (e.g. `response_format: json_object`) when available, falling back to prompt-based JSON instruction when not.

**FR-07.29**: Every structured output request SHALL include a validation schema. Responses that do not conform to the schema SHALL be treated as malformed (triggering retry/fallback per §4.2).

**FR-07.30**: The validation schema SHALL be defined alongside the prompt template (see S09) so that prompt and expected output format are versioned together.

---

## 9 — Generation Parameters

### 9.1 — Defaults and overrides

| Parameter | Default (generation) | Default (classification) | Default (extraction) |
|---|---|---|---|
| `temperature` | 0.8 | 0.1 | 0.2 |
| `top_p` | 0.95 | 0.5 | 0.8 |
| `max_tokens` | 1024 | 256 | 512 |
| `frequency_penalty` | 0.3 | 0.0 | 0.0 |
| `presence_penalty` | 0.3 | 0.0 | 0.0 |

**FR-07.31**: Each model role SHALL have configurable default generation parameters.

**FR-07.32**: Individual prompt templates (S09) MAY override generation parameters for their specific use case. Template overrides take precedence over role defaults.

**FR-07.33**: The system SHALL validate that generation parameter values are within acceptable ranges before sending to the provider.

---

## 10 — Error Handling

### 10.1 — Error taxonomy

| Error class | Examples | Handling |
|---|---|---|
| **Transient** | Rate limit (429), server error (5xx), timeout | Retry with backoff, then fallback |
| **Configuration** | Invalid API key, unknown model name | Fail fast, log critical error, do not retry |
| **Content** | Safety filter triggered, empty response, malformed JSON | Retry once (possibly with prompt adjustment), then fallback |
| **Budget** | Session cost cap exceeded, turn cost cap exceeded | Degrade gracefully per §6.2 |

**FR-07.34**: The system SHALL distinguish between transient and configuration errors. Transient errors trigger retry/fallback. Configuration errors fail immediately with a clear diagnostic.

**FR-07.35**: All errors SHALL be logged with: model role, model name, error type, request latency, and the trace ID.

**FR-07.36**: The system SHALL use exponential backoff with jitter for transient error retries. Maximum 2 retries on the same model before falling back.

### 10.2 — Total failure

**FR-07.37**: If all tiers fail for a turn, the system SHALL:
1. Return a pre-written "the story pauses" message to the player (not an error stack trace).
2. Preserve the player's input so it can be reprocessed when service recovers.
3. Emit a critical-severity alert to the observability backend.
4. Allow the player to retry the turn or continue with a fresh input.

---

## 11 — Observability

### 11.1 — Langfuse integration

**FR-07.38**: Every LLM call SHALL be recorded as a Langfuse **generation** event, including:
- Prompt messages (system + user + assistant history)
- Completion text
- Model name and provider
- Token counts (prompt, completion, total)
- Latency (time to first token, total time)
- Cost (computed from token counts and pricing)
- Generation parameters used
- Fallback tier (primary / fallback / last-resort)
- Trace ID linking to the parent turn trace

**FR-07.39**: LLM calls within a single turn SHALL be grouped under a single Langfuse **trace**, so that the full sequence of calls (classification → extraction → generation) is visible as one logical unit.

**FR-07.40**: The system SHALL tag Langfuse traces with: session ID, turn number, model role, and the prompt template version used.

### 11.2 — Metrics

The system SHALL expose the following metrics for monitoring and alerting:

| Metric | Type | Labels |
|---|---|---|
| `llm_call_duration_seconds` | Histogram | `role`, `model`, `tier`, `status` |
| `llm_call_tokens_total` | Counter | `role`, `model`, `direction` (prompt/completion) |
| `llm_call_cost_dollars` | Counter | `role`, `model` |
| `llm_call_errors_total` | Counter | `role`, `model`, `error_type` |
| `llm_fallback_total` | Counter | `role`, `from_tier`, `to_tier` |
| `llm_context_truncation_total` | Counter | `role`, `priority_level_truncated` |

---

## 12 — Testing

### 12.1 — Test modes

**FR-07.41**: The system SHALL support a **mock mode** where all LLM calls return deterministic, pre-configured responses. Mock mode is activated via configuration (e.g. environment variable), not code changes.

**FR-07.42**: Mock responses SHALL be configurable per model role, allowing tests to set up specific classification results, extraction outputs, or narrative text.

**FR-07.43**: In mock mode, the system SHALL still exercise the full call path (context assembly, token counting, response parsing) — only the actual HTTP call to the provider is replaced.

### 12.2 — Golden tests

**FR-07.44**: The system SHALL support **golden test** mode where LLM responses are recorded on first run and replayed on subsequent runs. This allows regression testing of prompt changes.

**FR-07.45**: Golden test fixtures SHALL include: the prompt sent, the response received, the model used, and the generation parameters. A test fails if the prompt changes without updating the golden fixture.

### 12.3 — What to assert

Tests of LLM-dependent code SHOULD assert:
- Response structure (does it parse? does it match the schema?)
- Token budget compliance (did the prompt fit the context window?)
- Fallback behavior (does the system degrade correctly when mocked to fail?)
- Cost tracking (are costs computed correctly from token counts?)
- Streaming (do SSE events arrive in the correct format?)

Tests SHOULD NOT assert exact text content of LLM responses (too brittle).

---

## 13 — Edge Cases

### EC-07.1 — Model returns repetitive output
The model generates text that loops or repeats. The system SHOULD detect repetitive output (e.g. same 50-char sequence appearing 3+ times) and truncate the response, requesting a fresh generation.

### EC-07.2 — Model returns content in wrong language
The system SHOULD validate that the response language matches the session's configured language. If mismatched, retry once, then fallback.

### EC-07.3 — Model hallucinates game state
The model references items, NPCs, or locations that don't exist in the world state. This is a generation quality issue handled by the pipeline (S08), not the LLM integration layer — but the integration layer SHOULD surface the raw response faithfully for the pipeline to validate.

### EC-07.4 — Provider changes API format
LiteLLM abstracts provider differences, but provider-specific quirks can still leak through. The integration layer SHOULD normalize response formats and log warnings when unexpected fields appear.

### EC-07.5 — Context window varies by model
When falling back to a model with a smaller context window, the system MUST re-compute the context budget for the new model's limits. A prompt that fit the primary model might not fit the fallback.

### EC-07.6 — Streaming connection drops mid-response
See FR-07.25. The partial response is preserved, and the next turn handles the continuation.

### EC-07.7 — Provider deprecates or removes a model
A model role's primary model is removed by the provider between configuration updates. The integration layer SHOULD detect invalid-model errors (e.g. HTTP 404 or provider-specific "model not found") and treat them as configuration errors — immediately falling back rather than retrying the same model. The system SHOULD log a critical alert so operators update the role configuration.

### EC-07.8 — Concurrent sessions exhaust shared rate limits
Multiple active sessions sharing the same API key may collectively exceed a provider's rate limit. The system SHOULD implement per-provider rate-limit awareness (e.g. tracking 429 headers) and distribute retries with jitter to avoid thundering-herd effects. Circuit-breaking (FR-07.11) partially addresses this, but operators SHOULD configure per-provider concurrency limits.

### EC-07.9 — Fallback model has smaller context window
When falling back to a model with a smaller context window, the system MUST recompute the context budget for the new model's limits before sending the prompt. A prompt that fit the primary model may need aggressive truncation for the fallback. See also EC-07.5.

### EC-07.10 — Structured output schema validation fails after fallback
The primary model supports native structured output (e.g. `response_format: json_object`), but the fallback model does not. The system SHOULD detect this capability mismatch and fall back to prompt-based JSON instruction for the weaker model (per FR-07.28), re-validating the output against the schema.

---

## 14 — Acceptance Criteria

### AC-07.1 — Model abstraction
- [ ] All LLM calls go through the unified interface.
- [ ] No caller references a provider-specific model name.
- [ ] Changing the model for a role requires only configuration changes, not code changes.
- [ ] The response envelope includes all fields specified in FR-07.02.

### AC-07.2 — Fallback behavior
- [ ] When the primary model times out, the fallback model is called within 1 second.
- [ ] When all tiers fail, the player sees a graceful message — never a stack trace or raw error.
- [ ] Circuit-breaking engages after configured failure threshold.
- [ ] Fallback tier used is recorded in every LLM call trace.

### AC-07.3 — Context window management
- [ ] A turn with excessive context (>50 conversation exchanges) completes without error.
- [ ] P0 content (system prompt, safety rules) is never truncated.
- [ ] Truncated conversation history is replaced with a summary, not silently dropped.
- [ ] Falling back to a smaller-context model re-computes the budget correctly.

### AC-07.4 — Streaming
- [ ] Narrative text appears token-by-token in the player's interface via SSE.
- [ ] Mid-stream disconnection does not corrupt session state.
- [ ] The `done` event includes accurate total token count.

### AC-07.5 — Cost management
- [ ] Per-turn and per-session costs are tracked and queryable.
- [ ] Session cost cap prevents runaway spending.
- [ ] Cost metrics are visible in the observability dashboard.

### AC-07.6 — Observability
- [ ] Every LLM call appears in Langfuse with prompt, completion, tokens, latency, and cost.
- [ ] All calls within a turn are grouped under one trace.
- [ ] Metrics are exposed for dashboarding and alerting.

### AC-07.7 — Testing
- [ ] Full test suite runs without any live LLM calls.
- [ ] Mock mode exercises the complete call path except the HTTP request.
- [ ] Golden tests detect unintended prompt changes.

---

## 15 — Out of Scope

The following are explicitly NOT covered by this spec:

- **Fine-tuning and model training** — TTA consumes pre-trained models via API; training workflows are a separate concern. — Deferred / not planned for v1.
- **Embedding generation and vector search** — Semantic retrieval is a world-model concern. — Handled in S04 (World Model) / S13 (World Graph Schema).
- **Provider-specific SDK usage** — The abstraction layer isolates callers from provider details; direct SDK calls are prohibited by FR-07.03. — By design.
- **Multi-modal input/output (images, audio, video)** — TTA is a text adventure; multi-modal generation is out of scope. — Deferred / not planned for v1.
- **Client-side or edge model execution** — All LLM inference is server-side. — Deferred.
- **Automated prompt optimization (DSPy-style tuning)** — Prompt authoring and tuning are content concerns. — Handled in S09.
- **Content moderation beyond provider safety filters** — Dedicated content safety is a separate system. — Handled in future S19 (Safety).

---

## 16 — Open Questions

| # | Question | Impact | Resolution needed by |
|---|---|---|---|
| Q-07.1 | Should we support multiple generation models simultaneously (e.g. different models for dialogue vs. description)? | Adds complexity to role system | Before S08 finalization |
| Q-07.2 | What is the maximum acceptable latency for a generation call before the player experience suffers? | Determines timeout defaults | Before alpha playtest |
| Q-07.3 | Should cost caps be per-player or per-deployment? | Determines cost control granularity | Before multi-tenant support |
| Q-07.4 | Do we need a token-level content filter in addition to provider-side safety filters? | Adds complexity, may duplicate effort | Before S19 (Safety) |

---

## Appendix A — Glossary

| Term | Definition |
|---|---|
| **Model role** | A logical purpose (generation, classification, extraction) mapped to a concrete model via configuration. |
| **Tier** | A fallback level (primary → fallback → last-resort). |
| **Context budget** | The maximum number of input tokens allocated for an LLM call, computed from the model's context window minus output reservation. |
| **Golden test** | A test that records an LLM response and replays it on subsequent runs for regression detection. |
| **SSE** | Server-Sent Events — the protocol used to stream tokens to the player's client. |
