# Prompt Variable Catalog

Reference for all template variables used by the TTA prompt system (S09).

## Architecture

Templates are **system-instruction-only** — they define LLM behavior, format,
and constraints. Player input and world context are passed as USER messages
by pipeline stages, never as template variables.

| Layer | Content |
|-------|---------|
| **Safety preamble** | Auto-prepended for `generation` and `classification` roles |
| **Template body** | System instructions rendered from `prompts/templates/` |
| **USER message** | Player input + world context (built by pipeline stages) |

## Template: `narrative.generate`

**File:** `prompts/templates/narrative/generate.prompt.md`
**Version:** 1.1.0
**Role:** `generation`

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `tone` | No | *(omitted)* | Narrative tone (e.g., "melancholic", "whimsical") |
| `word_min` | No | `"100"` | Minimum word count for response |
| `word_max` | No | `"200"` | Maximum word count for response |

## Template: `classification.intent`

**File:** `prompts/templates/classification/intent.prompt.md`
**Version:** 1.1.0
**Role:** `classification`

No variables — fully self-contained system instructions.

## Template: `extraction.world-changes`

**File:** `prompts/templates/extraction/world-changes.prompt.md`
**Version:** 1.1.0
**Role:** `extraction`

No variables — fully self-contained system instructions.

## Fragment: `safety-preamble`

**File:** `prompts/fragments/safety-preamble.fragment.md` *(if present)*

Auto-prepended to all templates with role `generation` or `classification`.
Not applied to `extraction` role templates.

## Injection Detection (Observe-Only)

User-supplied text passed in USER messages is scanned for injection patterns
by `log_injection_signals()` in both `generate_stage` and `understand_stage`.
Detection is **observe-only** — it logs warnings but never blocks or mutates input.

| Pattern | Trigger |
|---------|---------|
| `jinja_variable` | `{{` in text |
| `jinja_block` | `{%` in text |
| `system_prefix` | `SYSTEM:` at line start |
| `ignore_directive` | `IGNORE ... PREVIOUS` |

## Langfuse Trace Linkage

`record_llm_generation()` accepts prompt metadata fields for trace linkage.
These are populated **when the caller passes them**; not all pipeline paths
wire metadata through yet.

| Field | Source |
|-------|--------|
| `prompt_id` | Template ID (e.g., `narrative.generate`) |
| `prompt_version` | Template version (e.g., `1.1.0`) |
| `fragment_versions` | Hash map of included fragments |
| `prompt_hash` | SHA-256 prefix of rendered prompt text |
