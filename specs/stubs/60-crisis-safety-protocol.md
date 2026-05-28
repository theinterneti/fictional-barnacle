# S60 — Crisis Safety Protocol

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v5+
> **Implementation Fit**: ❌ Not Started
> **Level**: 4 — Operations
> **Dependencies**: S08 (Turn Pipeline), S24 (Content Moderation), S07 (LLM Integration)
> **Related**: S61 (Therapeutic Framework — gated on S60), S23 (Error Handling)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

S60 is the **gate spec** for S61. Before any therapeutic feature (CBT, mindfulness,
emotional support) is deployed, a robust crisis safety layer must be in place.

The core concern: a player may arrive in a dark emotional state and engage with TTA
as an indirect outlet. The game MUST detect signals of acute crisis (suicidal
ideation, self-harm) and respond with safety-first behavior — regardless of what
narrative is in progress.

S60 is explicitly **not** a general content moderation spec (S24 handles that).
S60 is a narrow, high-confidence detection and response protocol for acute crisis.

---

## 2. Detection Approach

Crisis detection uses a **two-tier model**:

| Tier | Method | Latency | Sensitivity |
|---|---|---|---|
| **T1 — Fast pattern match** | Regex + keyword list (curated by clinical consultants) | < 5 ms | High recall, lower precision |
| **T2 — LLM classifier** | Dedicated LLM call with crisis classification prompt | 300–800 ms | High precision |

T1 runs on every player input before the main turn pipeline. T2 is triggered only
when T1 returns a positive signal. If T2 confirms crisis, the safety response fires.
If T2 returns negative, the turn pipeline proceeds normally.

**Clinical review requirement**: Both the T1 keyword list and the T2 classifier
prompt MUST be reviewed and approved by a licensed mental health professional
before v5 is deployed.

---

## 3. Safety Response

When a confirmed crisis signal is detected:

1. **Interrupt**: the main turn pipeline is halted; the LLM does NOT generate
   game narration
2. **Step out of fiction**: a clearly-labeled, out-of-fiction message is
   delivered to the player (not in character, no narrative framing)
3. **Provide resources**: the message includes crisis hotline numbers appropriate
   to the player's configured locale (default: international resources)
4. **Offer continuation**: the player is told they can return to the story when
   ready, or end the session
5. **Log event**: a `crisis_signal_detected` event is logged (no PII; signal
   context hash only) for internal safety review
6. **No auto-notify**: TTA does NOT contact anyone on behalf of the player
   (respects player autonomy; no surveillance)

The out-of-fiction message is a fixed, human-written string (not LLM-generated).
It is localized per player locale.

---

## 4. Functional Requirements

### FR-60.01 — T1 Pattern Match

T1 runs synchronously in the turn pipeline ingress, before any LLM call.
T1 MUST complete within 5 ms. Pattern list is loaded from a static config file
(not from the database) to ensure availability even if services are degraded.

### FR-60.02 — T2 Classifier

T2 uses a dedicated LLM call via S07 with a fixed, audited prompt template
registered in S09 as `crisis_classifier`. Output is a structured JSON:
`{signal: bool, confidence: float, category: str}`. If the LLM call fails,
the system defaults to the T1 signal (fail-safe).

### FR-60.03 — Response Delivery

The safety response is delivered via the same transport as the current session
(SSE stream or WebSocket). It includes a `message_type: safety_response` field
so the client can render it with distinct styling.

### FR-60.04 — Audit Trail

Every T2 invocation is logged with `{timestamp, signal_hash, confidence, action_taken}`.
Logs are retained for 90 days for internal safety review. This is a dedicated audit
trail for safety events, distinct from the standard application log retention policy
defined in S17 (30 days).

### FR-60.05 — No Therapeutic Content Without S60

The S61 therapeutic framework module MUST NOT be loaded if S60 is not active.
This is enforced at application startup:

```python
if not settings.crisis_safety_enabled:
    raise ConfigurationError("S61 requires S60")
```

---

## 5. Acceptance Criteria (Gherkin)

```gherkin
Feature: Crisis Safety Protocol

  Scenario: AC-60.01 — T1 positive triggers T2
    Given player input contains a T1 crisis keyword
    When the turn ingress processes the input
    Then T2 classifier is invoked
    And the main turn pipeline is paused

  Scenario: AC-60.02 — T2 confirmed crisis delivers safety response
    Given T2 classifier returns signal=true, confidence=0.95
    When the safety response fires
    Then a non-fiction message with crisis resources is delivered
    And the game narrative is NOT generated
    And a crisis_signal_detected log event is emitted

  Scenario: AC-60.03 — T2 negative allows turn to proceed
    Given T1 triggers but T2 returns signal=false
    When T2 result is processed
    Then the main turn pipeline resumes
    And no safety message is delivered

  Scenario: AC-60.04 — T2 failure defaults to T1 signal
    Given T2 LLM call times out
    When the timeout occurs
    Then the T1 positive signal is treated as confirmed
    And the safety response fires
```

---

## 6. Out of Scope

- General content moderation (S24).
- Mandatory reporting or third-party notification.
- Long-term user support or follow-up.
- Diagnosis or clinical assessment.

---

## 7. Open Questions

| ID | Question | Status |
|---|----------|--------|
| OQ-60.01 | Which clinical consultant(s) will review T1 and T2 content? | 🔓 Open — external partnership required before v5 deployment. |
| OQ-60.02 | Which crisis resources are included by locale? | 🔓 Open — curated list to be assembled with clinical input. |
