# Skill: retain-to-hindsight

## Purpose
Store knowledge artifacts to Hindsight memory for persistent cross-session recall.

## When to invoke
After completing any task that produces durable knowledge:
- Architectural decision made
- Bug root-cause identified
- New pattern documented
- Design rationale for non-obvious choices

## How to invoke

Call `mcp__hindsight__retain` with:

| Field | Value |
|-------|-------|
| `bank_id` | Use the workspace bank for this project |
| `content` | Structured markdown (see format below) |
| `context` | Short category: `architectural-decision`, `pattern`, `failure`, `convention` |
| `tags` | Array: always include `tta-rebuild` + relevant tags |

## Content format

```markdown
## Context
<1-3 sentences: what prompted this>

## Decision / Finding
<The actual knowledge to remember>

## Rationale
<Why this matters for future work>
```

## Bank selection
- **Workspace bank** for TTA-rebuild-specific decisions (architecture, spec interpretations, tech choices)
- **`adam-global`** for cross-project patterns (Python conventions, tooling preferences, workflow habits)
