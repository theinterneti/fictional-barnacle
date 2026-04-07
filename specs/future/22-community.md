# S22 — Community

> **Status**: 📝 Stub (Future)
> **Level**: 5 — Future Vision
> **Dependencies**: S04, S09, S11
> **Last Updated**: 2025-07-24

## 1. Vision

A player community around TTA — sharing world templates, genre packs, custom content,
and stories. Think Steam Workshop meets writing community: players create, share, rate,
and remix game content.

Content types might include: world templates (pre-built world seeds), genre packs
(narrative styles, NPC archetypes), prompt packs (custom system prompts for different
experiences), and story collections (curated playthroughs).

## 2. v1 Constraints

These architectural decisions in v1 **must** accommodate future community features:

- **Portable content format**: Content assets — prompts, world templates, genre
  configurations — (S09) must use a documented, portable format that could be packaged
  and shared. No "magic constants" embedded in code.
- **Parameterized world generation**: World generation during Genesis (S02) and the
  world model (S04) must be parameterized enough that "world templates" are a natural
  extension — a template is just a set of parameters with documentation.
- **Engine/content separation**: The narrative engine (S03) and turn pipeline (S08)
  must cleanly separate engine logic from content configuration. Swapping genre packs
  should not require code changes.
- **Public profile capability**: The player identity system (S11) must support the
  concept of a public-facing profile — even if v1 profiles are private, the data model
  should accommodate a public view.
- **Content metadata**: All content assets (S09) must include metadata — author,
  version, description, tags, license — so that future community features can search,
  filter, and attribute content.
- **Moderation hooks**: The content pipeline should have insertion points where future
  moderation (human or automated) can review user-generated content before it's
  published to the community.

## 3. Not in v1

- No user-generated content sharing
- No community marketplace or library
- No content ratings or reviews
- No moderation system
- No public player profiles
- No content remixing or forking
- No community forums or discussion

## 4. Open Questions

1. Should community content be free, paid, or both?
2. How do we handle content quality in a user-generated marketplace?
3. What moderation model works — human review, AI moderation, community flagging?
4. How do we prevent prompt injection via user-generated content?
5. Should TTA maintain "official" content alongside community content?

## 5. Related Specs

| Spec | Relationship |
|------|-------------|
| S02 (Genesis) | World creation must be parameterized for templates |
| S04 (World Model) | Must support template-based world generation |
| S09 (Prompt & Content) | Must use portable, metadata-rich content format |
| S11 (Identity) | Must accommodate public profiles |
| S19 (Crisis Safety) | Community content needs safety review |
