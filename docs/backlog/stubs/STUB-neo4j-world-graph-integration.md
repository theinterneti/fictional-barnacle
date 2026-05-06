# Stub: Neo4j World Graph Integration Tests

**Horizon**: Long
**First surfaced**: 2026-05-03
**Status**: Awaiting Adam approval
**Discovery source**: Barnacle Gap Analysis — `make trace` + S13 spec review

## The Vision

Wire up a live Neo4j test environment so that the 9 [v2-gated] ACs in S13 can be validated: rich context queries (50ms location lookups, 200ms 2-hop nearby entities), atomic world-state mutations (movement, item pickup, NPC presence constraints), and dual-store consistency with SQL. This is the foundation for Dukat's "every action has a ripple effect" promise.

## Why Not Now

All AC-13.04–13.16 require a live Neo4j instance in the test environment. That's a CI/CD infrastructure change (S14), not a code change. Must wait for integration test harness (FB-004) to establish the pattern.

## Phases

- **Phase 1** (short): Add `neo4j` service to `docker-compose.test.yml`, write one smoke test that validates a 2-hop query (AC-13.06)
- **Phase 2** (mid): Implement atomic world-state mutations for movement + item pickup (AC-13.07–13.09); add all query performance assertions
- **Phase 3+** (long): Dual-store consistency between Neo4j and SQL (AC-13.15–13.16); full Dukat entity import pipeline

## Prerequisites

- FB-004 (Persistence SLA Test Harness) — establishes real-infra test patterns
- S14 (Deployment & Infrastructure) — CI must support `neo4j` in test containers
- Neo4j CE 5.x docker image pinned in compose file

## Evidence

- `specs/13-world-graph-schema.md` — AC-13.04–13.16 all marked [v2 — Neo4j]
- `make trace` output 2026-05-03 — 9 S13 ACs in uncovered list
- Dukat `Product_Specification.md §3` — "AI-Driven World Persistence: every action has a ripple effect"
- TTA `specs/persistence/neo4j-story-graph.md` — TTA's graph persistence spec as reference

## Adam's Notes

_(Left blank)_
