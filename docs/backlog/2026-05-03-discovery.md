# Discovery Report — 2026-05-03

**Mode**: Testing (dry-run)
**Sources**: TTA Intel · Dukat Oracle · Barnacle Gap · Hindsight · Web Research
**Candidates evaluated**: 8
**Tier 1 queued**: 1 (dry-run — not written to queue.yaml)

---

## Tier 1 — Would Queue Tonight

### [FB-001] Redis Session Cache Pattern — Port TTA's Redis TTL/Workflow State Architecture
- **Score**: 8.3 (Foundation: 10 · Spec_Coverage: 7 · TTA_Validation: 10 · Complexity: 7 · OSS_Fit: 5)
- **Horizon**: short–mid (first chunk: wire up workflow-state Redis keys; defer circuit-breaker persistence)
- **Specs**: [S12]
- **ACs**: [AC-12.05, AC-12.06, AC-12.07]
- **Evidence**: TTA `specs/persistence/redis-session-cache.md` + `src/player_experience/database/redis_cache.py` — fully specced, implemented, and CI-referenced. Barnacle's S12 spec explicitly calls out these ACs as unmet, and `make trace` confirms all three are uncovered. TTA's Redis TTL key schema (`session:{session_id}`, `orchestration:workflow:{workflow_id}`, `auth:tok:{sha256-prefix}`) is a direct port target.
- **Barnacle plan ref**: `plans/api-and-sessions.md`
- **Estimated tasks**: 4–5 (implement `redis_cache.py` equivalent in `src/tta/persistence/`, wire to turn pipeline, add integration test harness, validate AC-12.05 < 5 ms p95 + AC-12.06 < 500 ms)
- **Source**: TTA Intel + Barnacle Gap
- **Notes**: TTA's spec lists graceful degradation when Redis is unavailable (skip persistence, fall back to SQL) — that's the correct pattern for barnacle too. Port the TTL constants and key-naming convention verbatim.

---

## Tier 2 / 3 — Backlog

### [FB-002] SSE Reconnect + Missed-Event Replay (AC-10.05)
- **Score**: 7.7 — Tier 2
- **Horizon**: mid (Redis pub/sub architecture, 2 modules: `transport/sse.py` + Redis)
- **Specs**: [S10]
- **ACs**: [AC-10.05, AC-10.04]
- **Evidence**: Barnacle S10 spec explicitly calls out: "No SSE reconnect — AC-10.05 not implemented; Redis pub/sub architecture needed." TTA has `src/realtime/` area (242 symbols per GitNexus). `make trace` confirms both ACs uncovered.
- **Estimated tasks**: 5–6
- **Source**: Barnacle Gap + TTA Intel

### [FB-003] GDPR Deletion Background Job (AC-12.03)
- **Score**: 7.1 — Tier 2
- **Horizon**: short (single async worker, ~4 tasks)
- **Specs**: [S12]
- **ACs**: [AC-12.03]
- **Evidence**: S12 spec notes: "No GDPR purge job — AC-12.03 (deletion within 72h) depends on async background worker." TTA has `jobs/` module in barnacle src already. OSS fit: `arq` (Redis-based async job queue, already in stack).
- **Estimated tasks**: 4
- **Source**: Barnacle Gap

### [FB-004] Persistence SLA Integration Test Harness (AC-12.05–12.08)
- **Score**: 6.75 — Tier 2
- **Horizon**: mid (requires real Redis + Neo4j test infra, timing harness)
- **Specs**: [S12]
- **ACs**: [AC-12.05, AC-12.06, AC-12.07, AC-12.08]
- **Evidence**: S12 notes all four SLA ACs require "real Redis + timing harness" / "real Neo4j + timing harness." Blocked on test infra. TTA has similar integration test patterns.
- **Estimated tasks**: 7–8
- **Source**: Barnacle Gap

### [FB-005] Prompt Registry — Runtime Version Switching (AC-09.06, AC-09.07, AC-09.09)
- **Score**: 6.15 — Tier 2
- **Horizon**: short (single module `src/tta/prompts/`, ~3 tasks)
- **Specs**: [S09]
- **ACs**: [AC-09.06, AC-09.07, AC-09.09]
- **Evidence**: FR-09.06/07/09 specify runtime prompt registry with no-deploy version activation. `make trace` shows all three ACs uncovered. `src/tta/prompts/` module exists; needs registry layer.
- **Estimated tasks**: 3
- **Source**: Barnacle Gap

### [FB-006] TTA Agent Orchestration Protocol (IPA→WBA→NGA) — Evaluate for Barnacle
- **Score**: 6.0 — Tier 2 (borderline)
- **Horizon**: mid (barnacle's S08 spec explicitly rejects the IPA/WBA/NGA decomposition in favor of behavioral stages — this is about pattern evaluation, not direct port)
- **Specs**: [S08]
- **ACs**: [AC-08.07]
- **Evidence**: TTA has `src/agent_orchestration/` (366 symbols, 300 execution flows). Barnacle S08 spec says "The old TTA decomposed this into IPA→WBA→NGA. That decomposition had value, but it conflated behavior with architecture." — worth reviewing what TTA learned to inform barnacle's implementation.
- **Estimated tasks**: 2 (review + spec annotation only — no code)
- **Source**: TTA Intel

### [FB-007] World Graph Neo4j Rich Context Queries (AC-13.04–13.09) — Tier 3
- **Score**: 5.2 — Tier 3
- **Horizon**: long (requires live Neo4j integration test infra as prerequisite)
- **Specs**: [S13]
- **ACs**: [AC-13.04, AC-13.05, AC-13.06, AC-13.07, AC-13.08, AC-13.09]
- **Evidence**: S13 marks all six ACs as "[v2 — Neo4j]" gated. `make trace` confirms all uncovered.
- **Source**: Barnacle Gap

---

## Long-Term Stubs Created

- `STUB-neo4j-world-graph-integration.md` — Live Neo4j integration tests for AC-13.04–13.16
- `STUB-dukat-npc-dual-psychology.md` — Dukat's dual-aspect NPC psychology model (Radiant Heart / Shadow Self) — long-horizon narrative depth feature

---

## Adam's Signals (from Hindsight)

⚠️ Hindsight was unavailable in this run — all three banks (adam-global, fictional-barnacle, tta) could not be queried. Confidence reduced on priority ordering. No avoid/include signals surfaced.

---

## Dukat → Barnacle Signals

| World Feature Need | Dukat Doc Ref | Barnacle Spec Gap | Priority |
|---|---|---|---|
| AI-Driven World Persistence (graph-based, every action has ripple effect) | Product_Specification.md §3 | S13 ACs 04–09 not covered — no live Neo4j integration | high |
| Scalable graph architecture (millions of interconnected entities) | Product_Specification.md §5 (Secondary Goals) | S13 schema exists, no integration tests | high |
| Unified Prompt System / meta-prompting for style/lore consistency | Product_Specification.md §5 | S09 prompt registry ACs (09.06, 09.07, 09.09) uncovered | medium |
| Dual-aspect NPC Psychology (Radiant Heart vs Shadow Self, Big Five traits) | Product_Specification.md §3 | No barnacle spec for NPC psychology depth; S06 Character System is draft | medium |
| Data Consolidation Pipeline (JSON entity canonical format for Neo4j import) | Next_Phase_Roadmap.md Pillar 1 | S13/S12 — Dukat content ready to import but barnacle has no ingest pipeline | low |
| TLC Monk Council AI persona oversight | Product_Specification.md §3 | Therapeutic framework is S18 Stub — boundary constraints only, no implementation | low |

---

## Dropped

| Candidate | Score | Reason |
|-----------|-------|--------|
| Adaptive Difficulty in Narrative (Dukat §4) | < 4.0 | Post-v1; no barnacle spec; no TTA signal |
| Multiplayer Narrative Synchronization (Dukat SDD §2) | < 4.0 | Out of scope per S00 charter (single-player v1) |
| Neo4j Python OSS graph game libs (web research) | N/A | No credible 2025/2026 OSS candidate found; custom build required |
| PyLLaMA / narrative game engine OSS | N/A | Web research returned hallucinated URLs — no verified OSS match |

---

## Source Health

| Source | Status | Notes |
|--------|--------|-------|
| TTA Intel | ✅ OK | Read CHANGELOG.md, specs/agents/, specs/persistence/, src/ structure. TTA v1.0.0 production; agent orchestration + Redis cache fully implemented. |
| Dukat Oracle | ✅ OK | Read Product_Specification.md §§3–5, Next_Phase_Roadmap.md Pillar 1, SDD_Index.md. Dukat is pre-implementation data project; graph-first world model aligns with barnacle S13. |
| Barnacle Gap | ✅ OK | `make trace` ran successfully. 44 uncovered Approved ACs / 335 total. 86.9% coverage headline. S12, S13, S10, S09 are the highest-gap clusters. |
| Hindsight | ❌ UNAVAILABLE | mcp_hindsight_recall could not be reached in this run. Banks adam-global, fictional-barnacle, tta all skipped. |
| Web Research | ⚠️ DEGRADED | Sub-agent returned fabricated URLs (pyllama, narrative-game-engine). No verified OSS candidates surfaced. Treating OSS_Fit scores conservatively. |
