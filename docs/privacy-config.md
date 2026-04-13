# LLM Provider Data-Retention Configuration

> **Spec reference:** S17 Data Privacy — FR-17.29, FR-17.30

## Overview

TTA uses **LiteLLM** (library mode) to abstract LLM provider calls. Each provider
has different data-retention policies. This document describes how to configure
data-retention settings and what operators must verify before deploying.

## Provider Data-Retention Matrix

| Provider | Default Retention | Opt-Out Available | Config Key |
|----------|-------------------|-------------------|------------|
| OpenAI | 30 days (abuse monitoring) | Yes — via API org settings | `TTA_LITELLM_MODEL=openai/gpt-*` |
| Anthropic | 30 days (safety) | Yes — via usage policy | `TTA_LITELLM_MODEL=anthropic/claude-*` |
| Groq | Varies | Check current ToS | `TTA_LITELLM_MODEL=groq/*` |
| Local (Ollama) | None (self-hosted) | N/A | `TTA_LITELLM_MODEL=ollama/*` |

> **Operator responsibility:** Before deploying TTA, verify the data-retention
> policy of your chosen LLM provider and configure opt-out if available. TTA
> logs the active provider on startup (FR-17.30) so changes are auditable.

## Configuration

All LLM settings use the `TTA_` environment prefix:

```bash
# Primary model — determines which provider handles game narrative
TTA_LITELLM_MODEL=groq/llama-3.3-70b-versatile

# Optional: fallback model
TTA_LITELLM_FALLBACK_MODEL=openai/gpt-4o-mini
```

## Provider Change Logging (FR-17.30)

On application startup, TTA logs the configured LLM provider and model:

```
info: llm_provider_configured provider=groq model=groq/llama-3.3-70b-versatile
```

If the provider changes between deployments, the startup log makes the change
visible in your log aggregation system. Operators should set up alerts for
unexpected provider changes.

## Data Minimisation

TTA follows data-minimisation principles for LLM calls:

1. **No PII in prompts** — Player identifiers are UUIDs, not real names.
2. **Context windowing** — Only recent turns are sent; full history is never
   included in a single request.
3. **Prompt templates** — System prompts are version-controlled and auditable.

## Recommendations for Operators

1. **Review provider ToS** before each deployment.
2. **Prefer providers with opt-out** for data training if handling sensitive
   player narratives.
3. **Consider self-hosted models** (Ollama) for maximum data control.
4. **Monitor startup logs** for provider change events.
5. **Document your provider choice** in your deployment notes.
