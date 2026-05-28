# S70 — Routes, Distances, and Text Map

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.1 → v3
> **Implementation Fit**: ❌ Not Started
> **Level**: 2 — Simulation / Player Experience
> **Dependencies**: S04 (World Model), S13 (World Graph Schema), S29 (Universe as First-Class Entity), S33 (Universe Persistence Schema), S34 (Diegetic Time), S39 (Universe Composition Model)
> **Related**: `docs/vision/TTA-THREADS.md` Maps & Travel thread, S68 (Playtester Client Evolution)
> **Last Updated**: 2026-05-28

---

## 1. Purpose

Maps and travel become important before v4. v2.0 introduces spatial relationships, and v2.1 needs routes, distances, terrain, travel time, and minimal map output so players can understand where they are and make meaningful travel choices. This spec defines the next map/travel slice without promising v4 cross-universe maps or v5 dynamic discovery.

The deliverable is a text-first travel substrate: route edges in the world graph, travel metadata, route-aware encounters/challenges, and a minimal map representation usable by the v2.1 client and later v3 graphical map.

## 2. User Stories

- **As a** player, **I want** to know what places I can travel to from my current location, **so that** movement becomes a meaningful choice instead of narrative hand-waving.
- **As a** player, **I want** travel time and terrain to matter, **so that** a mountain path, city street, and sea voyage feel different.
- **As a** developer, **I want** route data stored in the world graph, **so that** future map UI and travel simulation can use the same substrate.
- **As a** narrative engine, **I want** route metadata available during generation, **so that** travel scenes can include appropriate challenges and discoveries.

## 3. Functional Requirements

### FR-70.01 — Route edge model

S70 extends S13's location graph with first-class `Route` nodes rather than assuming S13 already owns the schema. A v2.1 route is modeled as:

```cypher
(:Location)-[:ROUTE_START]->(:Route)-[:ROUTE_END]->(:Location)
```

Each `Route` node SHALL include:

- `route_id` (stable string ID)
- `label` (player-facing route label)
- `distance_value` and `distance_unit`
- `terrain_type` (`road`, `street`, `forest`, `mountain`, `water`, `interior`, `unknown`)
- `travel_modes` (subset of `walk`, `ride`, `vehicle`, `boat`, `fly`, `special`)
- `directionality` (`one_way` or `two_way`; Neo4j relationships remain directed, two-way routes are represented by query convention or paired edges)
- `discovery_scope` (`game` for v2.1; future `actor` scope reserved for S57)
- `discovery_state` (`known`, `undiscovered`, `hidden`)
- optional `blocked_reason`
- optional `encounter_tags`
- optional `coordinates` object reserved for v3 map specs

This is an explicit S70 delta to S13; S13 should be amended before S70 is promoted to Approved.

### FR-70.02 — Travel time calculation

The system SHALL calculate estimated travel time from `distance_value`, `distance_unit`, selected travel mode, `terrain_type`, `blocked_reason`, and an explicit numeric `travel_time_multiplier` on the Route node or universe manifest. No other hidden "world modifiers" participate in v2.1. The calculation may be approximate but must be deterministic for the same route state, selected mode, and multiplier inputs.

### FR-70.03 — Available route listing

Given a current location, the API/domain layer SHALL return a list of available routes with destination name, known/unknown status, estimated travel time when known, terrain label, and whether travel is currently blocked.

### FR-70.04 — Text map rendering

The system SHALL provide a minimal structured JSON local-map representation that S68 can render as text:

```json
{
  "current_location": {"location_id": "...", "name": "..."},
  "routes": [
    {
      "route_id": "...",
      "label": "North road",
      "destination": {"location_id": "...", "name": "..."},
      "terrain_type": "road",
      "travel_modes": ["walk"],
      "estimated_travel_time": {"value": 20, "unit": "minutes"},
      "blocked": false,
      "blocked_reason": null,
      "coordinates": null
    }
  ]
}
```

ASCII rendering is a client concern; the API/domain contract is JSON.

### FR-70.05 — Travel action resolution

When the player selects or types a travel action matching a known route, the turn pipeline SHALL resolve it as a travel intent, update current location when successful, and emit route context to the narrative engine. Location update and narrative emission use a two-phase turn outcome: validate route and compute destination first, generate narrative second, then commit the location change only with the accepted turn state. If narrative generation fails before the turn is accepted, current location remains unchanged and the retry path receives the same route context.

### FR-70.06 — Route-specific encounters and challenges

Routes MAY include encounter/challenge tags. The narrative engine can use these tags to introduce travel scenes, but route traversal must remain possible without generating a forced encounter every time. v2.1 uses deterministic encounter eligibility only: a route tag may set `encounter_eligible=true`, an optional cooldown key, and an optional S69 risk domain; probability tables and random encounter systems are deferred.

### FR-70.07 — Discovery and hidden routes

Routes can be undiscovered or hidden. Undiscovered routes are omitted from player-facing route lists unless the current game state reveals them. Hidden routes require specific S05 consequence/world-event conditions and must not leak through route-list, text-map, search, cache, or feedback payloads before discovery. v2.1 discovery state is scoped to the game/session; S57 may later narrow discovery to per-actor state for multiplayer.

### FR-70.08 — v3 map compatibility

Route data SHALL be stored in a way that future v3 graphical map and location browser can consume without re-modeling the world graph. Coordinates are optional in v2.1 and, when present, use `coordinates: {"x": number, "y": number, "space": "local"}`. Coordinate semantics beyond local 2D placement are deferred to the v3 map spec.

## 4. Non-Functional Requirements

### NFR-70.01 — Graph query budget

**Category**: Performance

**Target**: Listing available routes for the current location completes within 200 ms p95 against the expected v2.1 graph size in local/staging environments. The v2.1 performance assumption is up to 1,000 locations and 5,000 route nodes per universe unless S28 is updated with a different benchmark.

### NFR-70.02 — Deterministic travel estimates

**Category**: Consistency

**Target**: Travel time estimates do not vary between calls unless route state, player mode, world modifiers, or location state changes.

### NFR-70.03 — Content safety boundary

**Category**: Safety

**Target**: Encounter tags are context for narrative generation, not a bypass around content moderation or safety checks.

## 5. User Journeys

### Journey 1: Player chooses a known route

- **Trigger**: Player asks where they can go or opens the map panel.
- **Steps**:
  1. System lists known routes from the current location.
  2. Player chooses a route or types a matching travel command.
  3. System calculates travel time and resolves any blockers/challenges.
  4. Current location updates and narrative engine describes the journey/arrival.
- **Happy path**: Movement is clear, grounded, and reflected in state.
- **Alternative paths**: If the route is blocked, the player receives a reason and remains at the current location.

### Journey 2: Player discovers a hidden path

- **Trigger**: Player completes an action that reveals a hidden route.
- **Steps**:
  1. Route discovery state changes in the graph.
  2. Route appears in route listing/text map.
  3. Future travel actions can use the route.
- **Happy path**: Discovery feels like a persistent world change.

## 6. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | Current location has no known outgoing routes | Client receives an empty route list and narrative can suggest exploration instead of travel. |
| E2 | Route destination node is missing or corrupt | Route is excluded and a structured integrity warning is emitted. |
| E3 | Player attempts a blocked route | Current location does not change; narrative receives blocker reason. |
| E4 | Hidden route exists but is undiscovered | Route does not appear in player-facing route lists or map output. |
| E5 | Multiple routes lead to same destination | Listing disambiguates by route label/terrain/time. |
| E6 | Player uses free text that partially matches a route | System may ask clarification rather than picking silently. |
| E7 | Travel update succeeds but narrative generation fails | Location update follows the turn atomicity rules from existing pipeline/error specs; failures do not leak hidden route data or leave ambiguous current-location state. |

## 7. Acceptance Criteria (Gherkin)

```gherkin
Feature: Routes, distances, and text map

  Scenario: AC-70.01 known routes are listed from current location
    Given a current location with three known route edges
    When available routes are requested
    Then the response includes destination, terrain, travel modes, and estimated travel time for each route
    And blocked routes include a blocker reason

  Scenario: AC-70.02 travel time is deterministic
    Given a route with distance 10 km, terrain forest, and walking mode
    When travel time is calculated twice without route-state changes
    Then both estimates are equal

  Scenario: AC-70.03 text map hides undiscovered routes
    Given a current location has one known route and one hidden undiscovered route
    When the text map is rendered
    Then the known route is visible
    And the hidden route is not visible

  Scenario: AC-70.04 travel action updates current location
    Given the player is at location A
    And a known unblocked route connects A to location B
    When the player chooses that route
    Then the current location becomes B
    And the narrative engine receives route context for the travel scene

  Scenario: AC-70.05 blocked route prevents movement
    Given a route is marked blocked by a collapsed bridge
    When the player attempts to travel along that route
    Then current location remains unchanged
    And the player receives the blocker reason

  Scenario: AC-70.06 discovering a route changes future map output
    Given a hidden route exists from the current location
    When game state marks that route discovered
    Then future available-route and text-map responses include the route

  Scenario: AC-70.07 hidden routes do not leak through alternate surfaces
    Given a hidden route exists but is undiscovered
    When the player requests route lists, text maps, cached map state, or feedback context
    Then none of those payloads include the hidden route ID, label, destination, or encounter tags
```

### Criteria Checklist

- [ ] **AC-70.01**: Known routes list player-relevant travel metadata.
- [ ] **AC-70.02**: Travel time estimates are deterministic.
- [ ] **AC-70.03**: Hidden routes do not leak through maps.
- [ ] **AC-70.04**: Travel action updates current location and narrative context.
- [ ] **AC-70.05**: Blocked routes prevent movement with clear reasons.
- [ ] **AC-70.06**: Route discovery persists and changes map output.
- [ ] **AC-70.07**: Hidden route data does not leak through alternate surfaces.

## 8. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|---|---|---|
| S04 | World model | Locations/sites are the navigable entities. |
| S13 | World graph schema | Route edges and discovery state live in Neo4j-compatible graph data. |
| S29/S33 | Universe identity/persistence | Route state belongs to a universe and persists with it. |
| S34 | Diegetic time | Travel time estimates can advance diegetic time when a travel action succeeds. |
| S39 | Universe composition | Spatial hierarchy informs route generation and map grouping. |
| S68 | Client | Client renders available-route lists and text map output. |
| S69 | Systems/difficulty | Travel challenges can use mechanics resolution, but travel routes remain a world-state concern. |

## 9. Open Questions

1. Should curated v2.1 scenarios require manual route authoring, or can Genesis emit draft route nodes that an operator reviews before playtest? — *Impact: moderate* — *Owner: Genesis/world planning*

## 10. Out of Scope

- Graphical coordinate map, fog-of-war UI, and continent/region drill-down — v3 client/map work.
- Cross-universe maps, map sharing, or annotations — v4+ directional.
- Procedural unexplored-area generation and super-secrets — v5 directional.
- Resource-consumption travel simulation beyond travel time/blocker metadata — v3+.
- Full economy/trade route simulation — Economy component, not this route substrate spec.
