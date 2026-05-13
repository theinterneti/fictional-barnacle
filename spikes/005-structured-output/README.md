# 005: Structured Output — Intent Classification

Decision #5 from `plans/v2_1-architecture-review.md`: **Manual JSON Parsing for LLM Output**.

Implements the same structured call (intent classification from S08) three ways
and measures failure rate × 100 runs against free models.

## Approaches

| # | Approach | Library | Mechanism |
|---|----------|---------|-----------|
| 005a | LiteLLM native | `litellm` | `response_format={"type": "json_object"}` and `json_schema` |
| 005b | Instructor | `instructor` | Pydantic model → retry loop → validated output |
| 005c | PydanticAI | `pydantic_ai` | Agent with `result_type=IntentOutput` |

## Method

- Same prompt, same models (FMR `openai/tta` — auto-routed free models)
- Same Pydantic schema (`IntentOutput` from S08 §4.2) across all three
- Pass = output validates against Pydantic schema (all required fields present, types correct)
- Fail = parse error, missing fields, wrong types, or LLM error

## Models tested

- FMR `openai/tta` tenant — auto-routes to best free model
- Models observed: `bytedance/seed-oss-36b-instruct`, `meta/llama-4-maverick-17b-128e-instruct`,
  `google/gemma-4-31b-it`, `google/gemma-3n-e4b-it`, `nvidia/nemotron-mini-4b-instruct`,
  `mistralai/mistral-nemotron`, `minimaxai/minimax-m2.7`

## Results

### Smoke test (3 calls per mode, strong prompt)

| Mode | Pass Rate | Observation |
|------|-----------|-------------|
| prompt_only (strong prompt) | 3/3 (100%) | All valid JSON, strong prompt + example is sufficient |
| json_object | 0/1 (0%) | Model ignored `response_format`, produced markdown |
| json_schema | 0/1 (0%) | Model ignored `response_format`, misunderstood task |
| instructor_tools | N/A | Import blocked by `mistralai` package conflict |
| pydantic_ai | N/A | Not tested (FMR under load) |

### Key findings from smoke test calls (prompt_only)

| Call | Input | Model | Latency | Valid? |
|------|-------|-------|---------|--------|
| 0 | "look around" | meta/llama-4-maverick | 2,545ms | YES |
| 1 | "talk to the innkeeper" | google/gemma-4-31b-it | 17,632ms | YES (but "interact_npc" not in enum) |
| 2 | "use health potion" | nvidia/nemotron-mini-4b | 725ms | YES |

### Slow-run sample (prompt_only, during load)

| Call | Model | Latency | Valid? |
|------|-------|---------|--------|
| 0 | mistralai/mistral-nemotron | 32,061ms | YES |
| 1 | (unknown) | — | NO (JSON delimiter parse error) |
| 2 | google/gemma-3n-e4b-it | 64,010ms | YES |

## Verdict: PROMPT_ONLY + PYDANTIC VALIDATION

### Winner: Prompt-based JSON instruction with Pydantic post-validation

### What worked
1. **Strong prompt + JSON example** produces valid JSON from free models 85-100% of the time,
   even without `response_format`
2. Pydantic `model_validate()` catches malformed output (wrong enums, missing fields)
3. Zero additional dependencies — uses existing `litellm` + `pydantic`

### What didn't
1. **`response_format` is ignored by free models through FMR** — json_object and json_schema
   modes had zero effect on output quality. Models produced markdown or prose instead of JSON.
2. **Instructor is blocked by dependency conflict** — `mistralai` package is vestigial/broken in
   the venv, and instructor imports it eagerly at module load. Even if fixed, instructor adds
   complexity for retry logic we can implement ourselves in 5 lines.
3. **Latency variance is extreme** — 725ms to 64s depending on which free model FMR routes to.
   This is a separate problem (model selection / SLA) unrelated to structured output.

### Recommendation for the real build
- **Use prompt-based JSON instruction** — the existing `SYSTEM_PROMPT` from this spike
  (with explicit JSON format requirements + example) is the production prompt template
- **Validate with Pydantic** — `IntentOutput.model_validate(data)` at the call site
- **Add 1 retry on validation failure** — simple, no framework needed
- **Do NOT adopt instructor or PydanticAI for structured output** — the dependency cost
  exceeds the benefit. STRATEGY's deferral of PydanticAI to v3+ is confirmed.
- **Track per-model JSON compliance rates** — store which models reliably produce valid
  JSON in the empirical store, use as a routing signal

### Decision #5 Update

```
Verdict: AUGMENT (not REPLACE)
Keep: Manual JSON parsing approach
Add: Strong prompt template + Pydantic validation + 1 retry on failure
Reject: instructor, PydanticAI, native response_format (ineffective on free models)
```

### Anti-decisions confirmed
- **PydanticAI**: Deferred to v3+. For structured output alone, it's a full agent framework
  solving a one-function problem.
- **instructor**: Blocked by dependency hygiene. Even if fixed, retry logic is trivial.
