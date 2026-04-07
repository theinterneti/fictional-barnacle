# S21 — Collaborative Writing

> **Status**: 📝 Stub (Future)
> **Level**: 5 — Future Vision
> **Dependencies**: S01, S04, S06, S08, S10
> **Last Updated**: 2025-07-24

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
- **Session ≠ world**: The session model (S11) must be cleanly separable from the world
  model (S04). In multiplayer, multiple sessions share one world. v1 can have a 1:1
  mapping, but the data model must not make them inseparable.
- **Turn pipeline extensibility**: The turn processing pipeline (S08) must not hardcode
  single-player assumptions. Input processing should work on "a player's input" not
  "the input." Context assembly should accept a player ID parameter.
- **SSE → WebSocket migration path**: The streaming API (S10) must be designed so that
  SSE can be replaced with (or supplemented by) WebSocket without rewriting the
  narrative delivery layer. Abstract the transport.
- **Character identity separation**: The character system (S06) must cleanly separate
  character data from player data. In multiplayer, one player = one character, but
  the system should not merge these concepts.
- **Concurrent state mutation**: The world model (S04) and persistence layer (S12) must
  handle the possibility of concurrent modifications to shared state — or at minimum,
  not make assumptions that prevent adding concurrency control later.

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
