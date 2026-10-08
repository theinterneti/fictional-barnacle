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

## Appendix A: Implementation-Ready Sub-Tasks

Each high-level task above is expanded here into 2-5 minute sub-tasks with exact file paths, code, and verification commands. Use the existing `src/tta/models/v21_playtester.py` contracts as the foundation.

---

### A1. Task 1 Sub-Tasks: Pin Shared Data Contracts

The contract file `src/tta/models/v21_playtester.py` already exists with `TurnMetadata`, `MechanicsResolution`, `RouteNode`, `LocalMapResponse`, and `CorrelationIds`. These sub-tasks verify and extend those contracts.

#### A1.1: Verify existing contracts import cleanly

```bash
uv run python -c "from tta.models.v21_playtester import TurnMetadata, MechanicsResolution, RouteNode, LocalMapResponse; print('OK')"
# Expected: OK (no import errors)
```

#### A1.2: Add turn metadata integration test

**File:** `tests/unit/playtester/test_v21_contracts.py` (already exists)

Add verification that `TurnMetadata` serializes correctly for S10 turn requests:

```python
def test_turn_metadata_serialization():
    meta = TurnMetadata(input_source=TurnInputSource.suggested_choice)
    dumped = meta.model_dump()
    assert dumped["input_source"] == "suggested_choice"
    assert "correlation_ids" in dumped
```

```bash
uv run pytest tests/unit/playtester/test_v21_contracts.py -v
# Expected: all tests pass
```

#### A1.3: Verify RouteNode hides secrets

```python
def test_route_node_player_facing_hides_secret_metadata():
    route = RouteNode(
        route_id="r-1", from_location_id="a", to_location_id="b",
        label="Path", terrain_type="forest", distance_value=10, distance_unit="km",
        travel_modes=["walk"], discovery_state=RouteDiscoveryState.known,
        estimated_travel_time=TravelTimeEstimate(value=2, unit="hours"),
        secret_metadata={"spoiler": "bandit camp"}
    )
    dump = route.player_facing_dump()
    assert "spoiler" not in repr(dump)
    assert "secret_metadata" not in dump
```

---

### A2. Task 2 Sub-Tasks: Implement S70 Route Read Model

Uses the untracked RED test `tests/unit/world/test_s70_route_read_model.py` as the starting point.

#### A2.1: Add list_available_routes to Neo4jWorldService

**File:** `src/tta/world/neo4j_service.py`

```python
async def list_available_routes(self, session_id: UUID, location_id: str) -> list[RouteNode]:
    query = """
    MATCH (loc:Location {session_id: $sid, location_id: $location_id})
          -[:ROUTE_START]->(r:Route)-[:ROUTE_END]->(dest:Location {session_id: $sid})
    RETURN loc.location_id AS current_location_id, loc.name AS current_location_name,
           r.route_id, r.label, r.terrain_type, r.distance_value, r.distance_unit,
           r.travel_modes, r.directionality, r.discovery_state,
           r.blocked_reason, r.encounter_tags,
           dest.location_id AS to_location_id, dest.name AS to_location_name
    """
    records = [r async for r in await self._driver.session().run(query, sid=str(session_id), location_id=location_id)]
    return [_route_node_from_record(r, session_id) for r in records]
```

#### A2.2: Run RED tests

```bash
uv run pytest tests/unit/world/test_s70_route_read_model.py -v
# Expected: FAIL (Neo4jWorldService.list_available_routes doesn't exist yet)
# Then: implement and re-run
# Expected: PASS
```

#### A2.3: Implement get_local_map

**File:** `src/tta/world/neo4j_service.py`

```python
async def get_local_map(self, session_id: UUID) -> LocalMapResponse:
    # Get current location + routes
    routes = await self.list_available_routes(session_id, current_location_id)
    return LocalMapResponse(
        current_location_id=current_location_id,
        current_location_name=current_location_name,
        routes=routes
    )
```

```bash
uv run pytest tests/unit/world/test_s70_route_read_model.py::test_local_map_hides_undiscovered_routes_and_secret_metadata -v
git commit -m "feat(s70): add route read model with hidden-route filtering"
```

---

### A3. Task 3 Sub-Tasks: Implement S69 Mechanics Resolver

#### A3.1: Create deterministic mechanics classifier

**File:** Create `src/tta/mechanics/resolver.py`

```python
from tta.models.v21_playtester import (
    MechanicsRequest, MechanicsResolution, MechanicsResolutionResult,
    MechanicsConsequence, RiskLevel, MechanicsDomain
)

def classify_risk(request: MechanicsRequest) -> tuple[RiskLevel, MechanicsDomain]:
    """Deterministic v2.1 classification — no LLM call."""
    inp = request.player_input.lower()
    # Impossible actions
    if any(w in inp for w in ["fly", "teleport", "one-shot"]):
        return "impossible", "physical"
    # Risky actions
    if any(w in inp for w in ["attack", "steal", "climb", "sneak", "persuade", "cast"]):
        return "risky", _pick_domain(inp, request.available_domains)
    # Trivial actions
    if any(w in inp for w in ["look", "wait", "rest", "sit"]):
        return "trivial", "knowledge"
    return "uncertain", "physical"

def resolve(request: MechanicsRequest) -> MechanicsResolution:
    if request.play_mode == "narrative_only":
        return MechanicsResolution(
            resolution_id=_gen_id(), request=request,
            risk_level="trivial", domain="knowledge",
            result=MechanicsResolutionResult.skipped,
            consequence=MechanicsConsequence(summary="", narrative_constraint="")
        )
    risk, domain = classify_risk(request)
    result = _determine_outcome(risk, request.death_preference)
    return MechanicsResolution(
        resolution_id=_gen_id(), request=request,
        risk_level=risk, domain=domain, result=result,
        consequence=MechanicsConsequence(
            summary=f"{risk} {domain} action resolved as {result.value}",
            narrative_constraint=f"outcome={result.value}"
        )
    )
```

#### A3.2: Write TDD tests

```bash
uv run pytest tests/unit/mechanics/test_resolver.py -v
# Cycle: RED → GREEN → REFACTOR → commit
git commit -m "feat(s69): add deterministic mechanics resolver"
```

---

### A4. Task 4 Sub-Tasks: Implement S68 Client Shell

#### A4.1: Add playtester route to FastAPI app

**File:** `src/tta/api/routes/` — add playtester route

```python
@router.get("/playtester", response_class=HTMLResponse)
async def playtester_client(request: Request, invite_token: str = Query(...)):
    # Validate invite, serve styled HTML client
    return templates.TemplateResponse("playtester.html", {"invite_token": invite_token})
```

#### A4.2: Create playtester HTML template

**File:** Create `src/tta/templates/playtester.html`

Minimal styled client with transcript area, choice buttons, free-text input, feedback panel. Serves as server-rendered HTML + vanilla JS.

```bash
uv run pytest tests/unit/api/test_playtester_client.py -v
git commit -m "feat(s68): add same-origin playtester client shell"
```

---

### A5. Task 5 Sub-Tasks: Integrate Feedback into S43/S45

#### A5.1: Serialize S43-compatible feedback

**File:** `src/tta/api/routes/` — feedback endpoint

```python
@router.post("/playtester/feedback")
async def submit_feedback(
    feedback: FeedbackSubmission,
    request: Request
):
    record = feedback.to_s43_record()
    # Write to EVAL_HUMAN_FEEDBACK_DIR or configured export path
    export_path = Path(settings.eval_human_feedback_dir) / f"{feedback.game_id}_{feedback.turn_id}.json"
    export_path.write_text(record.model_dump_json())
    return {"status": "recorded"}
```

```bash
uv run pytest tests/unit/api/test_playtester_feedback.py -v
git commit -m "feat(s68): add S43-compatible playtester feedback export"
```

---

### A6. Task 6 Sub-Tasks: End-to-End Bundle Gate

```bash
# 1. Run all playtester contract tests
uv run pytest tests/unit/playtester/ -v

# 2. Run route read model tests
uv run pytest tests/unit/world/test_s70_route_read_model.py -v

# 3. Run mechanics resolver tests
uv run pytest tests/unit/mechanics/ -v

# 4. Validate specs
uv run python specs/index_specs.py --validate

# 5. Full gate
make gate
```
