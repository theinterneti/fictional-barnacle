# Stub: Dukat World Graph Integration

**Horizon**: Long / Epochal
**First surfaced**: 2026-05-04
**Status**: Awaiting Adam approval
**Discovery source**: Dukat sub-agent — Dukat/App Development/DukatDataModel.json

## The Vision

The Dukat world (characters, factions, locations, creatures, events, timelines) is
stored as structured JSON with a graph data model targeting Neo4j. fictional-barnacle
runs Neo4j as part of its core stack. Full integration would mean the barnacle engine
can query live Dukat world state during narrative generation — NPCs, factions, locations,
and consequences all pulled from a living graph rather than hardcoded into prompts.

## Why Not Now

The Dukat JSON datastores need consolidation and deduplication first (multiple parallel
files per entity type). The barnacle world graph schema (S13) must be fully implemented
before a second graph dataset can be integrated. This is at minimum a Phase 3 concern.

## Phases

- **Phase 1** (short): Audit Dukat JSON datastores — identify canonical files per entity
  type, document the entity schema. Output: `docs/dukat-entity-map.md`. 1–2 tasks.
- **Phase 2** (mid): Write a Dukat → barnacle graph importer. Maps Dukat entity types
  to S13 world graph schema. Import a small subset (1 region, ~50 entities) as proof.
- **Phase 3** (long): Full Dukat world loaded into barnacle's Neo4j. Narrative engine
  queries live world state. Genesis onboarding uses Dukat locations/factions.
- **Phase 4+** (epochal): Bidirectional — game events write back to Dukat world state.
  True persistent multiverse.

## Prerequisites

- S13 World Graph Schema fully implemented in barnacle
- S04 World Model implementation complete
- Dukat JSON datastores consolidated (Dukat/Next_Phase_Roadmap.md Pillar 1 done)
- barnacle Neo4j running and tested in CI (S14 deployment gate)

## Evidence

- `Dukat/App Development/DukatDataModel.json` — entity schema
- `Dukat/Next_Phase_Roadmap.md` — Pillar 1: Data Consolidation strategy
- `Dukat/Product_Specification.md` §5 — "Scalable Data Architecture" as core goal
- barnacle `specs/13-world-graph-schema.md` — the receiving schema
- barnacle `plans/world-and-genesis.md` — integration point

## Adam's Notes

<!-- Fill in here — any direction on timing, priority, or approach -->
