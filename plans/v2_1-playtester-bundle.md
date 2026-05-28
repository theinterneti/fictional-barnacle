# v2.1 Playtester Bundle Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Implement the v2.1 playtester slice across S68, S69, and S70 without letting client, mechanics, and map/travel contracts drift.

**Architecture:** S68 owns the same-origin playtester client and S43-compatible feedback capture. S69 owns deterministic v2.1 mechanics classification, player preferences, and milestone contracts. S70 owns first-class route nodes, deterministic travel estimates, and the JSON local-map contract rendered by S68.

**Tech Stack:** FastAPI/server-rendered HTML + JavaScript, existing S10 REST/SSE APIs, S11 player preferences, S12/S27 persistence, Neo4j route graph extensions, S43/S45 feedback ingestion.

---

## Bundle Scope

Included specs:

1. S68 — Playtester Client Evolution
2. S69 — World-Based Systems, Narrative Failure, and Milestones
3. S70 — Routes, Distances, and Text Map

Not included:

- Full account dashboard/OAuth.
- React/Svelte frontend migration.
- Full rules engine or D&D/5e compatibility.
- Graphical maps/fog-of-war UI.
- Community sharing, therapy layer, or multiverse features.

## Technology & Framework

The bundle stays inside the existing application stack:

- FastAPI serves the same-origin playtester client and existing S10 REST/SSE turn APIs.
- Neo4j stores the S70 `Route` graph extension alongside existing S13 world entities.
- Existing S11 player/session identity stores v2.1 play-mode and death-preference settings.
- Existing S12/S27 persistence records milestone state and route/mechanics correlations.
- Existing S43/S45 feedback/evaluation ingestion consumes S68 feedback records.

## Testing Strategy

Planning for the implementation phase should preserve this test shape:

- Unit tests for route visibility, deterministic travel-time calculation, and mechanics classification.
- Contract tests for `MechanicsResolution`, local-map JSON, and S43-compatible feedback records.
- Integration tests for same-origin client serving, turn submission metadata, and feedback ingestion.
- One no-spend end-to-end playtest using spy/no-op LLM seams to exercise S68 + S69 + S70 together.

## Interface Sketch

```python
class MechanicsResolverProtocol(Protocol):
    def resolve(self, request: MechanicsRequest) -> MechanicsResolution: ...

class LocalMapRoute(TypedDict):
    route_id: str
    from_location_id: str
    to_location_id: str
    discovered: bool
    travel_time: TravelTimeEstimate
```

This sketch is intentionally non-normative. The next implementation plan must bind the final module paths after inspecting the current API, persistence, and graph layers.

## Build Order

### Task 1: Pin shared data contracts

**Objective:** Create the minimal contract types before UI or pipeline work begins.

**Files:**
- Modify: S10/S11/S12/S27 implementation surfaces as needed by the implementation plan.
- Add or modify: route/mechanics/client contract modules selected during planning.

**Steps:**
1. Define S68 turn metadata keys: `input_source`, sanitized correlation IDs.
2. Define S69 `MechanicsResolution` and `MechanicsResolverProtocol`.
3. Define S70 route node shape and local-map JSON response.
4. Verify contracts can be serialized without exposing hidden routes or secret trace metadata.

### Task 2: Implement S70 route read model first

**Objective:** Make routes listable and renderable before travel mutation exists.

**Files:**
- Modify: Neo4j schema/query layer.
- Add tests for route listing, hidden-route filtering, deterministic travel estimates.

**Verification:**
- Known routes list with destination, terrain, modes, travel time.
- Hidden routes do not appear in route list, text-map JSON, cache payload, or feedback context.

### Task 3: Implement S69 deterministic mechanics resolver

**Objective:** Provide local/hybrid mechanics classification without adding mandatory LLM latency.

**Files:**
- Add resolver protocol/model.
- Add tests for trivial/uncertain/risky/impossible classification.
- Add milestone dedup tests.

**Verification:**
- Resolver returns `MechanicsResolution`, never final prose.
- No-death preference rewrites lethal failure into story consequence.
- Milestones deduplicate by required v2.1 keys.

### Task 4: Implement S68 same-origin client shell

**Objective:** Render the playable loop using the existing FastAPI deployment surface.

**Files:**
- Add server-rendered/static client assets under the API app.
- Add tests for same-origin serving, invite failure, turn metadata, and thinking state.

**Verification:**
- Client works without a separate frontend service.
- Choice buttons submit `input_source=suggested_choice`; free text submits `input_source=free_text`.
- Thinking/reconnecting state appears within 500 ms.

### Task 5: Integrate feedback into S43/S45

**Objective:** Ensure playtester feedback feeds the release-mode evaluation pipeline.

**Files:**
- Add S43-compatible feedback serialization/export path.
- Add tests that S45 can ingest a sample S68 feedback record.

**Verification:**
- Feedback includes game/session/turn IDs and sanitized trace/eval IDs.
- Feedback can include route/mechanics IDs when present.
- Raw prompt/provider metadata is not sent to browser or exported.

### Task 6: End-to-end bundle gate

**Objective:** Prove the three specs work as a slice.

**Scenario:**
1. Start a playtester session.
2. Select a suggested choice.
3. Attempt travel over a known route.
4. Resolve a risky travel challenge via S69.
5. Render local map via S70 in S68.
6. Submit S43-compatible feedback with route/mechanics correlation.

**Verification commands:**
- `uv run python specs/index_specs.py --validate`
- Relevant unit/integration tests selected by the implementation plan.
- Manual or automated playtest exercising the flow above.
