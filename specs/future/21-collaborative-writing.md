# S21 — Collaborative Writing

> **Status**: 📝 Stub (Future)
> **Level**: 5 — Future Vision
> **Dependencies**: S01, S04, S06, S08, S10
> **Last Updated**: 2026-04-09

## 1. Vision

Multiple players in the same world, co-authoring a story in real-time. Each player
controls their own character; the AI narrates the shared world. Think collaborative
improv theater with an AI director.

This transforms TTA from a solo experience into a social one — friends playing through
a story together, each seeing events from their character's perspective, with the AI
weaving their individual actions into a coherent shared narrative.

## 2. v1 Constraints

These architectural decisions in v1 **must** accommodate future multiplayer:

- **Multi-actor world model**: The world model (S04) must support multiple actors
  operating in the same world without hardcoding a single-player assumption. Locations,
  items, and NPCs should reference "actors" (plural), not "the player" (singular).
  - ⚠️ *v1 status: Partially fulfilled. World model uses `actor_id` in some places but pipeline entry points still assume single player.*
- **Session ≠ world**: The session model (S11) must be cleanly separable from the world
  model (S04). In multiplayer, multiple sessions share one world. v1 can have a 1:1
  mapping, but the data model must not make them inseparable.
  - ✅ *v1 status: Fulfilled. Session and world are separate models with a foreign key relationship.*
- **Turn pipeline extensibility**: The turn processing pipeline (S08) must not hardcode
  single-player assumptions. Input processing should work on "a player's input" not
  "the input." Context assembly should accept a player ID parameter.
  - ⚠️ *v1 status: Partially fulfilled. Pipeline accepts `player_input: str` — single input assumed. `player_id` is tracked but pipeline stages don't yet parameterize on it.*
- **SSE → WebSocket migration path**: The streaming API (S10) must be designed so that
  SSE can be replaced with (or supplemented by) WebSocket without rewriting the
  narrative delivery layer. Abstract the transport.
  - ❌ *v1 status: Not fulfilled. SSE streaming is hardcoded in `src/tta/api/sse.py` with no transport abstraction layer. Migration will require refactoring.*
- **Character identity separation**: The character system (S06) must cleanly separate
  character data from player data. In multiplayer, one player = one character, but
  the system should not merge these concepts.
  - ✅ *v1 status: Fulfilled. Player and Character are separate models.*
- **Concurrent state mutation**: The world model (S04) and persistence layer (S12) must
  handle the possibility of concurrent modifications to shared state — or at minimum,
  not make assumptions that prevent adding concurrency control later.
  - ✅ *v1 status: Fulfilled. PostgreSQL with row-level locking; turn processing is serialized per session.*

## 3. Not in v1

- No multiplayer sessions
- No real-time collaboration
- No WebSocket transport
- No shared world instances
- No turn ordering or conflict resolution
- No spectator mode
- No character-to-character interaction

## 4. Open Questions

1. Is multiplayer synchronous (real-time turns) or asynchronous (play-by-post)?
2. How does the AI handle conflicting player actions in the same turn?
3. Should all players see the same narrative, or character-specific perspectives?
4. How many players per world? 2? 4? Unlimited?
5. What's the minimum viable multiplayer experience?

## 5. Related Specs

| Spec | Relationship |
|------|-------------|
| S04 (World Model) | Must support multiple actors, not assume single player |
| S06 (Character System) | Must separate character from player identity |
| S08 (Turn Pipeline) | Must accept player ID, not assume single input |
| S10 (API & Streaming) | Must abstract transport for SSE→WS migration |
| S11 (Identity) | Session must be separable from world |
| S12 (Persistence) | Must not prevent concurrent state access |

## Changelog

- 2026-04-09: Added v1 progress status annotations to all 6 constraints in §2. Transport
  abstraction (constraint 4) is not fulfilled — SSE is hardcoded. Pipeline partially
  supports multi-player parameterization.
