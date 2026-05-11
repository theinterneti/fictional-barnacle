# Stub: Dukat NPC Dual-Aspect Psychology Model

**Horizon**: Long
**First surfaced**: 2026-05-03
**Status**: Awaiting Adam approval
**Discovery source**: Dukat Oracle — `Product_Specification.md §3`

## The Vision

Implement Dukat's dual-aspect NPC personality system in barnacle's Character System (S06): each NPC has a **Radiant Heart** (virtuous traits, growth arc) and a **Shadow Self** (destructive patterns, wound history), modelled using Big Five personality traits. The NPC's expressed behavior dynamically blends these two aspects based on narrative context, player relationship history, and in-world stressors.

## Why Not Now

S06 (Character System) is Draft and v1 Closed — the baseline NPC model needs to ship first. This is a post-v1 depth feature. No barnacle spec for NPC psychology exists yet; a new spec (S29 candidate) would be needed.

## Phases

- **Phase 1** (short): Write new barnacle spec S29-npc-psychology.md — define dual-aspect data model, Big Five trait storage schema, relationship to S06
- **Phase 2** (mid): Extend `src/tta/world/` NPC model with Radiant/Shadow fields; add LLM prompt instructions for trait-blending in S09 prompt registry
- **Phase 3+** (long): Dynamic NPC arc tracking (trait drift over sessions), therapeutic integration (S18 boundary), Dukat canonical NPC import

## Prerequisites

- S06 (Character System) v1 baseline implemented
- S12 (Persistence) — NPC trait history must be persisted
- S09 (Prompt Registry) — dynamic persona prompts

## Evidence

- `Dukat/Product_Specification.md §3` — "dual-aspect personality model (Radiant Heart vs. Shadow Self) and the Big Five personality traits"
- `Dukat/Product_Specification.md §4` — "Healer/Guide persona: monitor user sentiment, introduce healing opportunities"
- `Dukat/App Development/DukatDataModel.json` — character schema includes personality fields
- TTA `specs/therapeutic-safety/` — emotional safety layer that would interact with this system

## Adam's Notes

_(Left blank)_
