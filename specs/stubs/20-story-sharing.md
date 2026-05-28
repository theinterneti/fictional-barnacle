# S20 — Story Sharing

> **Status**: 📝 Stub (Future)
> **Level**: 5 — Future Vision
> **Dependencies**: S01, S03, S11, S12
> **Last Updated**: 2025-07-24

## 1. Vision

Players create incredible stories through gameplay. Those stories should be shareable —
not as raw chat logs, but as polished, readable narratives. Think of it like a
procedurally-generated novel that the player co-authored.

Features would include story export (PDF, ePub, web link), public story libraries,
"featured stories," reader comments, and social sharing. The best TTA stories become
marketing for TTA itself.

## 2. v1 Constraints

These architectural decisions in v1 **must** accommodate future story sharing:

- **Structured conversation history**: Session data (S12) must store conversation history
  with clear speaker attribution (narrator vs. player), turn boundaries, and chapter/arc
  markers — not a flat string dump.
- **Clean narrative prose**: The narrative engine (S03) must produce output that reads as
  good prose when extracted from the game context. No markdown artifacts, no system
  metadata in the text, no "[continue]" markers visible to readers.
- **Story arc tracking**: The gameplay loop (S01) must track narrative structure — acts,
  chapters, key moments, turning points — so future export can create well-structured
  documents rather than linear transcripts.
- **Consent model**: The player identity system (S11) must support consent flags —
  future sharing requires explicit player consent, and the data model should have
  a place for it.
- **Content separation**: Game state (world model, character stats) must be cleanly
  separable from narrative text — sharing exports the story, not the simulation data.

## 3. Not in v1

- No story export functionality
- No public story library or discovery
- No social sharing integration
- No reader comments or ratings
- No "featured stories" curation
- No story formatting or layout engine

## 4. Open Questions

1. Who owns a shared story — the player, TTA, or both?
2. How do we handle stories that reference AI-generated content and copyright?
3. Should shared stories include the player's choices, or just the narrative?
4. Can stories be shared anonymously?

## 5. Related Specs

| Spec | Relationship |
|------|-------------|
| S01 (Gameplay Loop) | Must track story structure (acts, chapters, moments) |
| S03 (Narrative Engine) | Must produce clean, shareable prose |
| S11 (Identity) | Must support consent flags for sharing |
| S12 (Persistence) | Must store structured, attributed history |
