# Generation Serving Profiles — Component Technical Plan

> **Phase**: SDD Phase 2 — Component Plan
> **Scope**: generation-serving-profile policy, LLM routing integration, evaluation/profile comparison, session preference plumbing
> **Input specs**: S64 (Generation Serving Profiles), S07 (LLM Integration), S45 (Evaluation Pipeline), S66 (Rate-Limit Budget & Task Prioritization)
> **Parent plans**: `plans/system.md`, `plans/llm-and-pipeline.md`, `plans/v2_1-evaluation-and-playtesting.md`
> **Implementation wave**: v2.2
> **Status**: 📝 Draft
> **Last Updated**: 2026-05-25

---

## 0. Why This Plan Exists

The current system has a real behavioral gap:
- generation role means different things in different clients
- batch playtesting can accidentally use interactive-serving assumptions
- latency/quality tradeoffs are not first-class or measurable

S64 defines the product contract. This plan defines the implementation that
makes the contract real without leaking provider/model internals into the API or
future UI.

This is not just a router tweak. It is a cross-cutting policy layer spanning:
- LLM client configuration
- request/session metadata
- playtester and evaluation orchestration
- observability
- FMR tenant/profile routing

---

## 1. Resolved Conflicts and Normative Decisions

### 1.1 Canonical profiles are policy objects, not raw config flags

`fast`, `balanced`, and `quality` are represented as a typed internal enum plus
structured policy objects. Code must not scatter ad hoc string checks like:
- `if quality:`
- `task = "creative"`
- `timeout = 90`

All generation routing decisions must resolve through the same profile-policy
lookup.

### 1.2 Profile applies to narrative generation only in v2.2

In v2.2, serving profile only affects generation-stage calls. Classification,
extraction, summarization, and other correctness-sensitive stages continue using
their existing role semantics.

### 1.3 Separate traffic class from serving profile

We need two independent dimensions:
- **serving profile**: `fast`, `balanced`, `quality`
- **traffic class**: `interactive_player`, `interactive_smoke`, `bulk_eval`, `quality_benchmark`

This prevents the previous mistake where playtesting semantics were inferred from
one overloaded task hint.

### 1.4 FMR integration must use explicit metadata

The LiteLLM/FMR boundary must receive explicit metadata for generation calls:
- serving profile
- traffic class
- router task

Do not rely on router-side guessing from prompt text or on client-specific enum
names.

### 1.5 Balanced is the system default everywhere

If no profile is supplied, `balanced` is the default for:
- gameplay sessions
- playtester agents
- evaluation runs

Callers must opt into `fast` or `quality` explicitly.

---

## 2. Technology / Framework Fit

This plan uses the existing TTA stack and does not introduce new infrastructure:
- Python 3.12 dataclasses / `StrEnum` for canonical policy types
- existing `LLMClient` / `LiteLLMClient` interfaces
- LiteLLM OpenAI-compatible request metadata for FMR routing hints
- existing structlog, Prometheus metrics, and Langfuse integration points
- existing pytest + AC traceability conventions for validation

---

## 3. Architecture Overview

### 3.1 New concepts

Add these shared types in `src/tta/llm/`:

```python
class GenerationServingProfile(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    QUALITY = "quality"


class GenerationTrafficClass(str, Enum):
    INTERACTIVE_PLAYER = "interactive_player"
    INTERACTIVE_SMOKE = "interactive_smoke"
    BULK_EVAL = "bulk_eval"
    QUALITY_BENCHMARK = "quality_benchmark"


class GenerationPolicy(BaseModel):
    profile: GenerationServingProfile
    router_task: str
    latency_class: str
    dispatch_preference: str
    timeout_seconds: float
    max_tokens: int
    degradation_chain: list[GenerationServingProfile]
```
These are implementation types, not API models yet.

### 3.2 Central policy resolver

Create a new module:

```text
src/tta/llm/serving_profiles.py
```

Responsibilities:
- canonical enums
- default profile lookup
- policy lookup by `(profile, traffic_class)`
- degradation rules
- serialization helpers for logs/metrics

Nothing else in the repo should hardcode generation routing policy.

### 3.3 LLM call path integration

Current generation call path:
- caller specifies `ModelRole.GENERATION`
- `LiteLLMClient` maps role -> router task
- requests are sent to router-backed models

New path:
- caller optionally specifies generation profile + traffic class
- `LiteLLMClient` resolves a `GenerationPolicy`
- generation request includes explicit routing metadata
- fallback/degradation happens through policy-aware logic

---

## 4. File-Level Changes

### 4.1 New files

Create:

- `specs/64-generation-serving-profiles.md`
- `plans/generation-serving-profiles.md`
- `src/tta/llm/serving_profiles.py`
- `tests/unit/llm/test_serving_profiles.py`
- `tests/unit/llm/test_litellm_serving_profiles.py`
- `tests/unit/eval/test_profile_matrix_planning.py`

### 4.2 Existing files to modify

#### LLM layer
- `src/tta/llm/client.py`
  - extend generation call interface to accept optional profile metadata
- `src/tta/llm/litellm_client.py`
  - replace hardcoded generation->creative mapping with policy resolution
- `src/tta/llm/roles.py`
  - keep role model mapping, but stop using it as the sole generation-policy layer
- `src/tta/llm/testing.py`
  - support profile-aware test doubles

#### Gameplay / API
- `src/tta/api/routes/games.py`
  - accept optional generation profile at session creation if exposed in v2.2
- `src/tta/models/game.py`
  - store canonical generation profile on session/game model if persisted in v2.2
- `src/tta/api/routes/games_lifecycle.py`
  - ensure restore/resume preserves stored profile

#### Pipeline / generation callers
- `src/tta/pipeline/stages/generate.py`
- `src/tta/genesis/genesis_lite.py`
- `src/tta/genesis/genesis_v2.py`
- `src/tta/quality/evaluator.py`
- `src/tta/playtest/agent.py`

These callers must explicitly pass traffic class, and generation profile where
relevant.

#### Eval layer
- `src/tta/eval/models.py`
  - extend batch config with serving-profile matrix support
- `src/tta/eval/pipeline.py`
  - plan and report by profile

#### Observability
- `src/tta/observability/langfuse.py`
- metric helpers / logging call sites in LLM path

Add labels/fields:
- requested_profile
- effective_profile
- degraded
- degradation_reason
- traffic_class

---

## 5. Data Model and API Contract

### 5.1 Internal client contract

Extend the generation interface in `src/tta/llm/client.py`.

Current shape is roughly:

```python
async def generate(role, messages, params=None) -> LLMResponse
```

Proposed shape:

```python
async def generate(
    role: ModelRole,
    messages: list[Message],
    params: GenerationParams | None = None,
    *,
    generation_profile: GenerationServingProfile | None = None,
    traffic_class: GenerationTrafficClass | None = None,
) -> LLMResponse
```

Rules:
- extra kwargs are only meaningful for `ModelRole.GENERATION`
- non-generation roles ignore them or reject them explicitly
- if omitted for generation, defaults are resolved centrally

### 5.2 LLMResponse extension

Extend `LLMResponse` with optional policy metadata:

```python
requested_profile: str = ""
effective_profile: str = ""
traffic_class: str = ""
degraded: bool = False
degradation_reason: str = ""
```

This keeps downstream logging and eval code simple.

### 5.3 Gameplay API surface

For v2.2, the safest public API step is session-level support on create/resume,
not per-turn slider churn.

Recommended request field on game/session creation:

```json
{
  "generation_profile": "balanced"
}
```

Validation:
- only `fast`, `balanced`, `quality`
- default omitted -> `balanced`

Persist on the session/game row if the repo’s current schema makes that easy.
If persistence is too invasive for the first slice, store it in session state
with an explicit follow-up task — but do not bury it in transient request-only
logic if you want resume to stay honest.

---

## 6. Policy Resolution Design

### 6.1 Canonical policy table

Initial v2.2 policy table:

| Profile | Traffic Class | router_task | latency_class | dispatch_preference | timeout | max_tokens |
|---|---|---|---|---|---:|---:|
| fast | interactive_player | generation | interactive | sync | 20s | 512 |
| balanced | interactive_player | generation | interactive | sync | 35s | 768 |
| quality | interactive_player | creative | relaxed | sync_or_compare | 60s | 1024 |
| fast | bulk_eval | generation | batch | queue_tolerant | 30s | 512 |
| balanced | bulk_eval | generation | batch | queue_tolerant | 45s | 768 |
| quality | quality_benchmark | creative | benchmark | queue_tolerant_or_compare | 90s | 1024 |

These values are starting points, not eternal truths. They should live in one
resolver module and be easy to retune.

### 6.2 Degradation algorithm

Pseudo-logic:

```python
def degradation_chain(profile):
    if profile == QUALITY:
        return [QUALITY, BALANCED, FAST]
    if profile == BALANCED:
        return [BALANCED, FAST]
    return [FAST]
```

When generation fails for supply/policy reasons that warrant profile degradation:
1. try requested profile policy
2. if exhausted and degradation allowed, try next profile
3. record requested/effective profile and reason
4. if all profiles fail, raise the existing LLM failure

Important: this is not a replacement for normal primary/fallback within a single
profile. The nesting is:
- profile policy resolution
- within profile: normal model fallback chain
- across profiles: explicit degradation only when justified

### 6.3 What counts as degradable

Allow profile degradation on:
- router/provider exhaustion
- 503 no providers available
- explicit policy envelope unavailable
- queue timeout for a higher profile

Do not degrade on:
- caller validation errors
- malformed prompts
- schema violations in non-generation tasks
- persistence failures

---

## 7. FMR / Router Integration

### 7.1 Explicit request metadata

At the LiteLLM call boundary, generation requests should include:

```python
call_kwargs["task"] = policy.router_task
call_kwargs["generation_profile"] = policy.profile.value
call_kwargs["traffic_class"] = traffic_class.value
```

If LiteLLM/OpenAI compatibility rejects unknown fields for the current path,
fallback to `extra_body={...}` rather than losing metadata.

### 7.2 Tenant strategy

Near-term recommendation: do not create one tenant per profile immediately if a
profile header/body field is enough.

But do create profile-aware routing/pinned pools in FMR terms, likely using:
- explicit task hints
- traffic_class awareness
- optional alias/tenant split for bulk evaluation lanes

Recommended rollout:
1. phase 1: metadata only, current tenant intact
2. phase 2: split bulk-eval / quality-benchmark routing into dedicated FMR lanes
3. phase 3: optional player-profile-aware pinning if frontier data justifies it

### 7.3 No more implicit generation->creative default

The current hardcoded behavior in `litellm_client.py` is the main bug vector.
After this change:
- `creative` should only be chosen by profile policy
- not by every generation call automatically

---

## 8. Playtester and Evaluation Changes

### 8.1 BatchConfig extension

Extend `BatchConfig` in `src/tta/eval/models.py`:

```python
serving_profiles: list[GenerationServingProfile] = field(
    default_factory=lambda: [GenerationServingProfile.BALANCED]
)
traffic_class: GenerationTrafficClass = GenerationTrafficClass.BULK_EVAL
```

This changes planning semantics from:
- seeds × personas × reps

to:
- profiles × seeds × personas × reps

### 8.2 PlannedRun extension

Add to `PlannedRun`:

```python
generation_profile: str
traffic_class: str
```

### 8.3 RunResult / BatchEvalResult extension

Add per-run and per-batch profile visibility:
- profile on `RunResult`
- grouped medians by profile in `BatchEvalResult`
- frontier-friendly artifact output

### 8.4 Playtester agent defaults

`PlaytesterAgent` should default to:
- profile = `balanced`
- traffic_class = `bulk_eval` when run from eval pipeline
- traffic_class = `interactive_smoke` when used in smoke validation mode

That distinction must be explicit at construction time, not inferred from URL or
call stack.

---

## 9. Observability Design

### 9.1 Structured logs

For every generation call completion/failure, log:

```python
log.info(
    "llm_generation_call_complete",
    requested_profile=...,
    effective_profile=...,
    degraded=...,
    degradation_reason=...,
    traffic_class=...,
    router_task=...,
    model=...,
    latency_ms=...,
)
```

### 9.2 Metrics

Add labels or new metrics for:
- generation_calls_total{requested_profile,effective_profile,traffic_class,status}
- generation_latency_seconds{effective_profile,traffic_class}
- generation_degradations_total{from_profile,to_profile,reason}

### 9.3 Langfuse

Attach serving profile metadata to traces/scores so profile-based trend analysis
is possible in Langfuse without custom joins.

---

## 10. Testing Strategy

### 10.1 Unit tests

#### `tests/unit/llm/test_serving_profiles.py`
Cover:
- default profile resolution
- policy lookup by `(profile, traffic_class)`
- degradation chain correctness
- invalid-profile rejection

#### `tests/unit/llm/test_litellm_serving_profiles.py`
Cover:
- generation calls inject explicit profile metadata
- generation does not default to `creative` blindly
- degradation updates effective profile fields correctly
- non-generation roles ignore or reject profile extras correctly

#### `tests/unit/eval/test_profile_matrix_planning.py`
Cover:
- planning runs across multiple profiles
- artifact grouping by profile
- defaulting to balanced when omitted

### 10.2 Integration tests

Add/extend tests for:
- session create with `generation_profile`
- resume/restore preserving profile
- live smoke running under `fast` vs `balanced`

### 10.3 Evaluation validation

Add one smoke-friendly comparison mode:
- same seed/persona under `fast` and `balanced`
- verify outputs are emitted with distinct profile labels
- do not assert one profile is always “better”; assert metrics are recorded

---

## 11. Rollout Phases

### Phase 1 — Tactical isolation + central policy layer

Goal: stop the current routing ambiguity.

Steps:
1. add serving profile enums and resolver module
2. patch `LiteLLMClient` to use central policy instead of hardcoded creative mapping
3. make bulk playtester/eval traffic explicit with `balanced + bulk_eval`
4. add observability fields

Outcome:
- current bug class is eliminated
- no UI required yet

### Phase 2 — Profile-aware evaluation frontier

Goal: learn the latency/quality frontier.

Steps:
1. extend BatchConfig to support profile matrices
2. emit profile-aware artifacts
3. run repeated seed/persona comparisons
4. establish provisional latency targets and preferred defaults

Outcome:
- empirical frontier data for future product/UI work

### Phase 3 — Session/player preference plumbing

Goal: make profile selectable in actual sessions.

Steps:
1. add API/session field
2. persist and restore profile
3. expose profile in admin/debug views

Outcome:
- real player/session policy support

### Phase 4 — UI slider / labels

Goal: expose the feature in a player-facing way.

Steps:
1. map user-facing labels to canonical profiles
2. instrument usage and preference
3. tune labels from research

Outcome:
- productized control backed by measured data

---

## 12. Risks and Mitigations

| Risk | Why it matters | Mitigation |
|---|---|---|
| Profile semantics drift over time | Slider becomes meaningless | Centralize policy + track requested/effective profile in artifacts |
| Too many profile-specific code paths | Logic becomes unmaintainable | Keep profile handling in one resolver module |
| Bulk eval still competes with interactive traffic | Old problem survives under new names | Make traffic_class explicit and route-aware |
| Numeric latency targets are unrealistic | Product promise breaks | Learn targets from Phase 2 eval frontier data |
| Persistence work is bigger than expected | Delays useful fix | Ship Phase 1 without player-persisted preference if needed |

---

## 13. Recommended Immediate Implementation Sequence

1. Create `src/tta/llm/serving_profiles.py`
2. Extend `LLMClient` interface for optional profile metadata
3. Patch `LiteLLMClient` to resolve generation policy centrally
4. Remove hardcoded generation -> creative behavior
5. Mark playtester/eval traffic as `balanced + bulk_eval`
6. Add observability fields to generation calls
7. Extend eval models for multi-profile planning
8. Add tests

That gets the architecture onto the right rails before any player-facing UI or
bigger API changes.

---

## 14. Verification Checklist

Before considering S64 implementation complete:

- [ ] No generation caller relies on ad hoc `creative` defaults
- [ ] Generation serving profile is centrally resolved
- [ ] Bulk evaluation traffic carries explicit profile + traffic class metadata
- [ ] Requested/effective profile is visible in logs/traces
- [ ] Eval artifacts can compare multiple profiles on the same matrix
- [ ] Session/profile defaults are explicit and tested
- [ ] Resume/restore behavior is defined for persisted profile state

---

## 15. Open Implementation Decisions

1. Should unknown OpenAI-compatible request fields go into top-level body or
   `extra_body` for LiteLLM/FMR compatibility?
2. Is session-level persistence for `generation_profile` cheap enough for Phase 1,
   or should it wait for Phase 3?
3. Do we need a distinct FMR tenant for `bulk_eval` immediately, or is metadata
   enough until Phase 2 data arrives?
4. Should `quality` ever use comparison dispatch for live gameplay, or only for
   explicit benchmark traffic?

---

## 16. Notes for the Current Hotfix Context

This plan intentionally preserves the immediate tactical direction:
- do not fix the current playtesting issue by prompt trimming
- do not treat all generation as `creative`
- do separate batch evaluation semantics from interactive player semantics

The first code change should therefore be the central policy resolver and the
removal of the current hardcoded generation->creative mapping.
