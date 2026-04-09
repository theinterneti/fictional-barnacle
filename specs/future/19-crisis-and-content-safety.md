# S19 — Crisis & Content Safety

> **Status**: 📝 Stub (Future)
> **Level**: 5 — Future Vision
> **Dependencies**: S08, S10, S12
> **Last Updated**: 2026-04-09

## 1. Vision

A multi-layered safety system that detects crisis signals in player input, validates
generated content for emotional safety, and can intervene in real-time — interrupting
narrative streams, escalating to human professionals, and providing immediate support
resources.

The old TTA designed a 4-level crisis detection system (LOW/MODERATE/HIGH/CRITICAL) and
a 5-level emotional safety scale (SAFE → CAUTION → ELEVATED → HIGH_RISK → CRISIS). The
concepts are sound; the implementation needs to be rebuilt with the benefit of hindsight.

## 2. v1 Constraints

These architectural decisions in v1 **must** accommodate future safety systems:

- **Pipeline hook points**: The turn processing pipeline (S08) must have clearly defined
  hook points where safety checks can be inserted — both pre-generation (input screening)
  and post-generation (output validation) — without restructuring the pipeline.
  - ✅ *v1 status: Fulfilled. S24 content moderation uses pipeline hooks for pre/post checks.*
- **Stream interruption**: The SSE streaming protocol (S10) must support mid-stream
  interruption. If a safety system flags generated content, the stream must be stoppable
  and replaceable with a safety response.
  - ⚠️ *v1 status: Not yet implemented. No abort/cancel endpoint exists. Needed before this stub can be promoted.*
- **Session flagging**: The session data model (S11, S12) must support flag/tag metadata
  on sessions and individual turns — safety systems need to mark sessions for review.
  - ✅ *v1 status: Fulfilled. Player model has status + suspended_reason fields; turn model supports metadata.*
- **Audit trail**: All pipeline processing (S08) must produce audit-friendly logs that
  could later support safety review. Not detailed safety logs — just enough structure
  that a future safety system can add its own.
  - ✅ *v1 status: Fulfilled. structlog + OTel tracing covers all pipeline stages.*
- **Content classification hooks**: The narrative engine (S03) must not assume all
  generated content is safe to deliver. A future content classifier needs a clean
  insertion point.
  - ✅ *v1 status: Fulfilled. S24 moderation inserts post-generation classification.*
- **Graceful degradation**: If a future safety check fails or times out, the system
  must have a defined fallback behavior (e.g., pause and ask for clarification rather
  than deliver potentially unsafe content).
  - ✅ *v1 status: Partially fulfilled. S23 error handling provides fallback patterns; S24 moderation has configurable fail-open/fail-closed.*

## 3. Not in v1

- No crisis detection or classification
- No real-time content safety scoring
- No automatic escalation to professionals
- No crisis hotline integration
- No content filtering or moderation
- No emotional state tracking for safety purposes
- No mandatory safety review of generated content

## 4. Open Questions

1. What liability does TTA assume if a player in crisis uses the game?
2. Should v1 include a simple disclaimer or terms of service about not being a crisis tool?
3. How aggressive should future content filtering be? (False positives kill fun.)
4. Should safety be an opt-in layer or always-on?

## 5. Related Specs

| Spec | Relationship |
|------|-------------|
| S08 (Turn Pipeline) | Must have pre/post-generation hook points |
| S10 (API & Streaming) | Must support mid-stream interruption |
| S11 (Identity & Sessions) | Must support session/turn flagging |
| S12 (Persistence) | Must store auditable processing records |
| S18 (Therapeutic) | Complementary — safety enables therapy |

## Changelog

- 2026-04-09: Added v1 progress status annotations to all 6 constraints in §2. S24
  Content Moderation now fulfills 5/6 constraints. Stream interruption (constraint 2)
  remains unimplemented.
