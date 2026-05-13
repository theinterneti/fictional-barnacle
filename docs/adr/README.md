# Architecture Decision Records

## ADR-001: Instructor for Structured LLM Output

**Date**: 2026-05-13
**Status**: Accepted
**Decision**: Add `instructor` (≥1.7, <2) as a production dependency for structured LLM output extraction.

### Context

The TTA pipeline has ~15 call sites that parse JSON from LLM responses using `json.loads()` wrapped in `try/except`. These include:

- Character trait extraction (genesis_v2.py)
- Composition extraction (genesis_v2.py)
- Commentary parsing (playtest/agent.py)
- Quality evaluation scoring (quality/evaluator.py)
- Snapshot deserialization (game/snapshot.py)

Each call site must handle:
1. The LLM wrapping JSON in markdown code blocks
2. Missing or extra fields
3. Type mismatches (string instead of number, etc.)
4. Complete parse failures

Instructor solves all of these with Pydantic model validation, automatic retries, and a consistent API across 15+ LLM providers.

### Alternatives Considered

| Option | Verdict | Reason |
|--------|---------|--------|
| **Instructor** | **Chosen** | Most popular Python structured output lib (3M monthly downloads, 11K stars). Works with LiteLLM, Pydantic-native, MIT licensed. |
| Outlines | Rejected | Requires local model inference (token-level constraints). Doesn't work with API-based providers like our FMR backend. |
| PydanticAI | Rejected | Full agent framework — overkill. We deliberately avoid agent frameworks for the main pipeline. |
| Continue manual json.loads | Rejected | Works but fragile. Each call site reinvents validation. Instructor collapses ~8 lines of try/except + type checking into 1 type-safe call. |

### Integration Pattern

```python
from pydantic import BaseModel, Field
from tta.llm.structured import generate_structured

class CharacterTraits(BaseModel):
    traits: list[str] = Field(max_length=3)

result = await generate_structured(
    llm_client,
    messages=[...],
    response_model=CharacterTraits,
)
# result.traits is guaranteed list[str] with ≤3 items
```

Key design choices:
- **Lazy import**: Instructor imports `litellm` which hangs when CWD is the project root. The structured module uses lazy initialization via `_get_instructor_client()`.
- **from_litellm(), not from_provider()**: Model selection is controlled by our existing role configs, not hardcoded strings.
- **Non-fatal by convention**: Callers still wrap in try/except — structured extraction is best-effort.

### Migration Plan

Existing `json.loads()` call sites will be converted opportunistically. The genesis_v2.py `_infer_traits` method is the first conversion. No rush — each conversion is a net improvement in type safety and error handling.

---

## ADR-002: Neo4j as Optional World Graph Backend

**Date**: 2026-05-13
**Status**: Accepted (reaffirmed)
**Decision**: Keep Neo4j CE 5.x as an optional backend. Promote InMemoryWorldService as the default for development and single-session play. Require Neo4j only for multi-session universe persistence and complex graph traversals.

### Context

Neo4j provides Cypher-based graph queries for world state (locations, NPCs, items, relationships, memory records). It adds operational complexity: container dependency, auth, backup, separate migration path.

The InMemoryWorldService (Python dicts) already handles all tests and single-session play. For a game where a player might spend hundreds or thousands of hours, the question is: at what scale does in-memory storage become insufficient?

### Scale Analysis

| Component | Per-Session Estimate | 1000-Hour Estimate | In-Memory Viable? |
|-----------|---------------------|-------------------|-------------------|
| Locations | 50–200 | 2,000–10,000 | Yes (Python dict: O(1) lookup) |
| NPCs | 10–50 active | 500–2,000 total | Yes |
| Items | 20–100 | 1,000–5,000 | Yes |
| MemoryRecords | 100–500 | 50,000–200,000 | Borderline (compression keeps hot set small) |
| NPC social edges | 50–500 | 10,000–50,000 | Graph traversal needed |

The bottleneck isn't memory (Python dicts can hold millions of nodes) — it's **graph traversal complexity**. Queries like "all NPCs who know each other within 3 hops" or "consequence propagation through the world graph" become O(n²) in pure Python. Neo4j's Cypher engine handles these in O(n) with index-backed traversals.

### Decision

- **InMemoryWorldService** remains the default for development and single-session play
- **Neo4jWorldService** is required for:
  - Multi-session universe persistence (S33)
  - NPC social graph queries (S38)
  - Consequence propagation (S36)
  - World memory compression (S37)

The Neo4j startup migration path is preserved — new v2 tables and indexes are additive. The `TTA_NEO4J_URI` env var controls whether Neo4j is used; when unset, the app falls back to InMemoryWorldService.

### Why Not Alternatives

| Option | Verdict | Reason |
|--------|---------|--------|
| **Neo4j CE 5.x** | **Kept** | Cypher queries, graph traversal, active community. Container overhead is acceptable for the graph query power. |
| networkx (in-memory) | Rejected | No persistence. Graph algorithms are Python-only (slower). Would need custom serialization for universe snapshots. |
| SQL recursive CTEs | Rejected | Postgres can do graph traversal via recursive CTEs, but the syntax is painful and performance degrades beyond 3-4 hops. |
| SurrealDB / ArcadeDB | Not evaluated | Multi-model databases with graph support exist, but Neo4j's Cypher + ecosystem maturity outweigh potential consolidation benefits at our scale. |
