# TTA Spec Portfolio Control Plane

> **Status**: Working portfolio map
> **Purpose**: Rebase the spec portfolio on the current vision threads and decide which components should receive next-step specs now.
> **Source vision docs**: `docs/vision/TTA-UNIFIED-VISION.md`, `docs/vision/TTA-THREADS.md`, `docs/vision/TTA-STRATEGY.md`, `docs/vision/TTA-CRITICAL-REVIEW.md`
> **Last Updated**: 2026-05-28

---

## 1. Portfolio Principle

The vision is thread-based; the spec portfolio needs to be component-based. Threads describe how capabilities mature across v1→v5. Components are the control plane for SDD: they decide where specs, technical plans, tests, and implementation lanes belong.

Specability boundary:

- **v1–v2.1**: specable as executable behavior with concrete acceptance criteria.
- **v3**: mixed, but production/player-facing substrate is specable now when it has measurable runtime contracts.
- **v4**: mostly directional; promote only narrow feasibility/research specs.
- **v5**: boundary stubs only until v4 learnings exist.

This document intentionally prevents fake implementation specs for speculative areas. If a component cannot produce testable ACs now, it stays a boundary stub, research spec, or feasibility spike.

---

## 2. Canonical Components

| Component | Role | Vision threads rolled in | Primary existing specs | Current phase status | Portfolio decision |
|---|---|---|---|---|---|
| Simulation & World State | Persistent universe, graph schema, time, memory, NPC autonomy, consequences | Simulation Depth, NPC Society, Worlds/Content, Save/Load, Context Engineering | S04, S12, S13, S27, S29-S40 | v2.0 substrate mostly spec-complete; v2.1 quality hooks remain tied to evaluation | Do not add broad new simulation specs this session; only close open schema/quality gates when implementation catches up. |
| Gameplay & Narrative Engine | Turn loop, narrative generation, choice/consequence, scene structure | Gameplay Loop, Narrative Engine, Scenes, Concepts, Prompt Engineering | S01, S03, S05, S07-S09, S41, S44-S45, S64, S66 | Core loop and LLM substrate are spec-complete for current phase; v3 beat/scene work is not fully grounded yet | Keep decision-matrix and TLC-style narration as spikes/research, not implementation specs. |
| Genesis & World Authoring | First-time world creation and content richness at rest | Onboarding & Genesis, Worlds/Content, Concepts, Image Generation | S02, S40, S41, S44-S45 | v2.0 Genesis v2 is specified; v2.1 richness budget exists in vision but not portfolio | Needs later v2.1 content-richness spec after Genesis smoke evidence; not one of this session's top four. |
| Systems, Difficulty & Progression | Formal mechanics, risk/failure, milestones, achievements | Game Systems, Difficulty & Failure, Progression & Achievements, Economy | S01, S05, S06, S39, new S69 | Under-specced relative to v2.1/v3 vision | **Spec now**: S69 establishes v2.1 world-based mechanics, narrative failure, and milestones without overcommitting v4/v5 systems. |
| Quality, Evaluation & Safety | Playtesting, evals, moderation, privacy, safety gates | Quality & Evaluation, Safety, Self-Improving Narrative, Critical Review gates | S16-S17, S23-S25, S42-S45, S60, S66-S67 | Strong v1/v2.1 coverage; therapeutic/crisis layers remain future | Keep full therapeutic framework out of current implementation specs; use narrow safety/eval specs only. |
| Player Experience & Client | Web UI, first-time journey, invite playtesting, character sheet/map surfaces | UI/Client, Player Experience, Save/Load, Maps/Travel, Sharing | S10-S11, S27, new S68 | Critical review identified a web-client gap | **Spec now**: S68 defines playtester-ready v2.1 client evolution and v3-ready seams. |
| Infrastructure & Operations | Runtime, deploy, worker, CI/live services, scaling, resilience | Infrastructure, Observability, Testing, Error Handling, Player Experience distribution | S14-S17, S26, S28, S46-S49, S65-S67 | Existing S46-S49 drafts are specable but needed SDD polish | **Spec now/remediate now**: S46-S49 are the production-runtime next-major-step cluster. |
| Sharing, Social & Community | Story export, character passport, community templates, multiplayer | Sharing & Community, Multiplayer, Scenes, Player Experience | future/S20-S22, S59, S62-S63 | Story export is narrow/specable soon; community suite is not | Maybe next: story export slice only. Keep community/UGW as boundary stubs. |
| Future Therapeutic Layer | Personality-as-mechanic now; therapy later | Therapeutic Depth, Safety, TLC Monks, Dukat-derived theory | future/S18-S19, S60-S61 | Not specable as full framework | Boundary stubs/research only. No concrete therapeutic implementation spec this session. |

---

## 3. Cross-Cutting Control Lanes

| Cross-cutting lane | Owns | Existing specs/plans | Current decision |
|---|---|---|---|
| Context / Prompt / Model Routing | Prompt templates, Langfuse prompt versions, FMR task tiers, model-routing constraints | S07, S09, S64, S66; `plans/generation-serving-profiles.md`, `plans/prompts.md` | Spec-complete enough for v2.1 rate/budget work; future prompt self-improvement remains directional. |
| Observability / Testing / Resilience | Local/CI gates, live DB tests, restore drills, runtime metrics, error handling | S15, S16, S23, S28, S47, S65-S67 | Active control lane for all production runtime specs. |
| Content / Concept / Scene Tooling | Scenario seeds, concept maps, scene tracking/export, image prompts | S41, S44-S45, S70, future scene work | Needs narrow v2.1/v3 specs, not grand v5 authoring platform specs. |

---

## 4. Existing Spec Classification

### Spec-complete for current phase

- Foundation/core: S00-S17 except duplicate S15 governance issue noted below.
- Core game and v2 simulation: S01-S13, S23-S40.
- Evaluation/playtesting substrate: S42-S45 are approved, but some still have validator polish warnings in `specs/index.md`; treat as polish, not conceptual blockers.
- Local automation/process: S65-S67.
- Generation routing/rate-budget: S64 and S66, with AC-66.04 explicitly deferred to the provider-utilization spike/plan.

### Needs next-step specs or remediation now

- **Infrastructure & Operations**: S46-S49 form the v3 production runtime cluster. They were already drafted but lacked full SDD shape. This session remediates them with user stories and edge cases so they are ready for review/planning.
- **Player Experience & Client**: S68 fills the web-client gap called out by critical review §7.
- **Systems, Difficulty & Progression**: S69 fills the v2.1/v3 mechanics gap created by the vision's Game Systems, Difficulty, and Progression threads.
- **Maps/Travel**: S70 fills the v2.1/v3 spatial navigation gap, grounded in existing universe/location schema and avoiding v4/v5 cross-universe promises.

### Maybe next, but not this control-plane pass

- **Story export / sharing**: narrow v3 story export is specable, especially from save/scene data. Full community sharing is not.
- **Image generation**: basic v2.1/v3 optional portraits/locations are specable if framed as manual/optional generation with no style-consistency promises. Full media pipeline is not.
- **Genesis content richness**: should wait for Genesis v2 smoke evidence or be framed as a numeric richness budget spec.

### Directional only / boundary stubs

- Full therapeutic framework: future/S18, S61, and v5 healing framework remain directional until v4 research/prototype evidence.
- Community/user-generated worlds: future/S22 and S63 remain boundary stubs until solo play and story export are validated.
- Multiverse/cross-universe suite: S50-S58 contain useful boundary language but are v4+ directional unless reduced to research spikes.
- Dukat-heavy concept architecture: theoretical reference only; require fresh validation before scheduling.

---

## 5. Current Governance Hazards

| Hazard | Evidence | Control decision |
|---|---|---|
| Resolved duplicate S15 | `specs/71-langfuse-integration.md` now carries the Langfuse extension; `specs/15-observability.md` remains the approved S15 baseline | Route future Langfuse work by S71; S15 remains the approved observability baseline. |
| Future stubs counted as warnings | `specs/future/*` have no ACs by design | Treat warnings as expected for boundary stubs; do not "fix" by inventing fake ACs. |
| Draft v4/v5 specs look implementation-shaped | S50-S58, S61-S63 have Gherkin but no stories/edge cases and target speculative layers | Keep as boundary/research until version gate, except narrow story-export slice if promoted later. |
| Root worktree stale | Durable repo note says root is stale; current work uses `.worktrees/fb013-performance-ac2808-plan` | Continue spec/portfolio work in the clean main worktree; avoid root WIP. |

---

## 6. Session Work Products

This control-plane pass creates or remediates the following next-major-step artifacts:

| Component | Artifact | Type | Why now |
|---|---|---|---|
| Infrastructure & Operations | S46-S49 remediation | Draft-spec remediation | Production runtime is specable and needed before v3 hosting/multi-player work. |
| Player Experience & Client | S68 — Playtester Client Evolution | New draft spec | Critical review calls out the web-client gap; v2.1 needs a playtester-ready client before external feedback. |
| Systems, Difficulty & Progression | S69 — World-Based Systems, Narrative Failure, and Milestones | New draft spec | Vision says systems/difficulty/progression begin in v2.1, but portfolio had no focused spec. |
| Maps/Travel | S70 — Routes, Distances, and Text Map | New draft spec | Maps/travel mature in v2.0/v2.1 and are under-specced relative to importance. |

---

## 7. Recommended Next Sequence

1. Run spec validation and keep S46-S49, S68-S70 warning-free.
2. Review the production runtime cluster as a cluster, not four isolated specs: S46 deploy target, S47 live graph CI, S48 async runner, S49 multi-instance sessions.
3. Plan S68 before any public/playtester UX work.
4. Plan S69 and S70 only after confirming they do not conflict with active v2.0 simulation implementation.
5. Leave sharing/image generation for the next portfolio pass unless there is remaining session capacity after validators are clean.


### External Review Artifacts

- `docs/spec-review-2026-05-28.md` — independent review of the older draft portfolio. Its still-relevant blockers are tracked as portfolio hazards; this pass resolved the duplicate S15 by renumbering the Langfuse extension to S71 and remediated the v3 operations topology/affinity issues in S46-S49. Findings already superseded on this worktree include the former local CI gate draft and the S50 rate-limit collision, now resolved by S65 and S66.
- `docs/spec-review-2026-05-28-s68-s70.md` — independent supplemental review of S68-S70. This remediation pass folds in the high-confidence fixes: S68 feedback alignment with S43/S45, S69 preference and mechanics-result contracts, S70 explicit S13 route-schema delta, and a bundle plan for S68-S70.
