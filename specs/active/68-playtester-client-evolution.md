# S68 — Playtester Client Evolution

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.1 → v3
> **Implementation Fit**: ❌ Not Started
> **Level**: 6 — Player Experience & Client
> **Dependencies**: S01 (Gameplay Loop), S02 (Genesis Onboarding), S05 (Choice & Consequence), S10 (API & Streaming), S11 (Player Identity & Sessions), S27 (Save/Load & Game Management), S43 (Human Playtester Program), S45 (Evaluation Pipeline)
> **Related**: S42-S45 (Evaluation & Playtesting), `docs/vision/TTA-CRITICAL-REVIEW.md` §7, `docs/vision/TTA-THREADS.md` UI / Client and Player Experience threads
> **Last Updated**: 2026-05-28

---

## 1. Purpose

TTA's current client is acceptable for developer testing, but the vision now requires invited playtesters in v2.1 and player-ready hosted access in v3. This spec defines the next client step: a styled web client that supports readable streaming prose, choice buttons alongside free-text input, basic session/game management, and an embedded feedback path without adopting a full frontend framework prematurely.

The goal is not a mature app. The goal is a playtester-ready client that proves the loop is enjoyable enough to share and creates stable seams for the v3 character sheet, map, and account dashboard.

## 2. User Stories

- **As a** playtester, **I want** a readable web interface with styled narrative output, **so that** I can play without curl, terminal commands, or raw SSE details.
- **As a** playtester, **I want** choice buttons and free-text input in the same turn composer, **so that** I can either follow suggested actions or improvise.
- **As a** developer, **I want** feedback tied to game/session/turn IDs, **so that** v2.1 quality review can correlate human feedback with traces and transcripts.
- **As an** operator, **I want** the v2.1 client to remain simple and same-origin, **so that** it does not add an unproven frontend build/deploy substrate before v3.

## 3. Functional Requirements

### FR-68.01 — Styled streaming transcript

The client SHALL render streamed narrative output in a styled transcript area that preserves paragraph breaks, distinguishes system/status events from narrative prose, and keeps the latest turn visible without requiring manual scroll management.

### FR-68.02 — Dual-mode turn composer

The composer SHALL support both free-text submission and server-provided choice buttons. Clicking a choice submits a normal turn using S10's optional `metadata` object with `input_source=suggested_choice`; free text submits with `input_source=free_text`. S68 does not change the required S10 turn-request fields.

### FR-68.03 — Basic playtester session shell

The client SHALL expose a minimal session shell: current game title and turn count from S10 game metadata, current location name from the S10 game-state response when available, save/load affordance, and reconnect status. It MUST NOT require user-created accounts for v2.1; anonymous S11 player identity still exists server-side.

### FR-68.04 — Feedback capture

After each completed turn, the client SHALL offer lightweight feedback: rating, optional text note, and category tags such as `confusing`, `slow`, `great_moment`, `tone_issue`, and `bug`. Feedback SHALL be serialized as an S43-compatible human feedback record so S45 release-mode ingestion can read it from `EVAL_HUMAN_FEEDBACK_DIR` or the configured equivalent export path. Payloads include game ID, session ID, turn ID, optional route ID, optional mechanics result ID, and sanitized trace/evaluation correlation IDs when available. They MUST NOT expose raw prompt text, provider credentials, provider request metadata, or secret-bearing trace fields to the browser.

### FR-68.05 — Invite-link access boundary

For v2.1, access MAY be controlled by an invite token or local operator configuration, but the spec does not require full user accounts. Invite tokens are bearer capability tokens: they SHALL be time-bounded, revocable by the operator, and bound server-side to an anonymous S11 player identity or playtest participant record when first used. A missing, expired, revoked, or invalid invite token must fail with a human-readable access message rather than exposing a broken page.

### FR-68.06 — Progressive enhancement only

The v2.1 client SHALL work as server-rendered/static HTML + JavaScript served by the existing FastAPI app, reusing the current same-origin HTML response surface rather than creating a separate frontend deployment. React/Svelte adoption is deferred to the v3 architecture review trigger described in `docs/vision/TTA-STRATEGY.md`.

### FR-68.07 — v3 extension seams

The client state model SHALL reserve stable extension points for character sheet, inventory, and map panels without implementing those panels in v2.1. The reserved seam IDs are:

- `client.panel.character_sheet` — future character/profile panel mount point.
- `client.panel.inventory` — future inventory/equipment panel mount point.
- `client.panel.map` — S70 route/text-map panel mount point, later graphical map mount point.
- `client.event.turn_submitted` — emitted with `game_id`, `session_id`, `turn_id`, and `input_source`.
- `client.event.turn_completed` — emitted with `game_id`, `session_id`, `turn_id`, and sanitized correlation IDs.
- `client.event.feedback_submitted` — emitted after S43-compatible feedback is accepted or queued for retry.

These seams are documented IDs/events/contracts, not hidden ad hoc DOM state.

## 4. Non-Functional Requirements

### NFR-68.01 — Playtester latency visibility

**Category**: Usability / Observability

**Target**: The client shows a non-intrusive "thinking/streaming/reconnecting" state within 500 ms of turn submission or connection loss.

### NFR-68.02 — Accessibility floor

**Category**: Accessibility

**Target**: The client uses semantic buttons/forms, visible focus states, and live-region semantics for streaming output. Full WCAG conformance is out of scope for v2.1.

### NFR-68.03 — No new deploy surface

**Category**: Operations

**Target**: The v2.1 client ships in the existing Docker image and does not require a separate frontend build service, CDN, or Node runtime in production.

## 5. User Journeys

### Journey 1: Playtester starts and completes a turn

- **Trigger**: A playtester opens an invite link.
- **Steps**:
  1. The client validates access and loads the current or new game session.
  2. The playtester reads the styled transcript.
  3. The playtester chooses a suggested action or types a custom action.
  4. The client shows thinking/streaming state while receiving SSE events.
  5. The transcript updates and feedback controls appear for the completed turn.
- **Happy path**: The playtester can continue playing without understanding the API.
- **Alternative paths**: If SSE disconnects, reconnect status appears and the client resumes or offers refresh without losing submitted text.

### Journey 2: Developer reviews human feedback

- **Trigger**: A playtester submits feedback after a turn.
- **Steps**:
  1. Feedback is stored with game/session/turn identifiers.
  2. The developer correlates feedback with logs/traces/transcript.
  3. Quality issues feed into v2.1 evaluation decisions.
- **Happy path**: Feedback points to the exact generation event that produced the experience.

## 6. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | SSE stream disconnects mid-turn | Client shows reconnecting state and resumes from server-supported event recovery, or asks the player to refresh without duplicate submission. |
| E2 | Choice button is clicked twice | Client disables pending controls until the turn request resolves. |
| E3 | Feedback submit fails | Client preserves the note locally and offers retry; play can continue. |
| E4 | Invite token is invalid or expired | Client shows an access-denied message with no raw stack trace. |
| E5 | Server provides no choices for a turn | Free-text composer remains available; the layout does not break. |
| E6 | Player navigates away with unsent text | Browser warns or preserves draft text in local page state. |
| E7 | Streaming output includes system/status events | Status events render distinctly from narrative prose and are not merged into story text. |

## 7. Acceptance Criteria (Gherkin)

```gherkin
Feature: Playtester client evolution

  Scenario: AC-68.01 styled streaming output is readable
    Given a playtester has an active game session
    When the API streams narrative and status events for a turn
    Then narrative prose is appended to the transcript with paragraph breaks preserved
    And status events are visually distinct from narrative text

  Scenario: AC-68.02 choice buttons submit normal turns
    Given the current turn response includes suggested choices
    When the playtester clicks a choice button
    Then the client submits a turn request using the choice text
    And the request metadata includes input_source = "suggested_choice"

  Scenario: AC-68.03 free-text input remains available
    Given suggested choices are visible
    When the playtester types a custom action and submits it
    Then the client submits the custom text as the turn input
    And the request metadata includes input_source = "free_text"

  Scenario: AC-68.04 feedback is correlated to a completed turn
    Given a turn has completed
    When the playtester submits rating, tags, and an optional note
    Then the feedback payload includes game_id, session_id, turn_id, and sanitized trace or evaluation correlation IDs when available
    And the payload is compatible with the S43 human feedback record consumed by S45
    And the client confirms feedback was recorded or offers retry on failure

  Scenario: AC-68.05 v2.1 client has no separate deploy surface
    Given the Docker image is built for the API
    When the web client route is requested
    Then the client assets are served by the existing FastAPI deployment
    And no separate frontend service is required

  Scenario: AC-68.06 invalid invite fails clearly
    Given an invalid invite token
    When the playtester opens the client URL
    Then the client displays an access-denied message
    And no game session is created

  Scenario: AC-68.07 thinking state appears promptly
    Given a playtester submits a turn
    When the turn request is accepted or the stream connection drops
    Then the client displays thinking, streaming, or reconnecting state within 500 ms
```

### Criteria Checklist

- [ ] **AC-68.01**: Styled streaming output is readable and event-aware.
- [ ] **AC-68.02**: Choice buttons submit normal turn requests with source metadata.
- [ ] **AC-68.03**: Free-text input remains available alongside choices.
- [ ] **AC-68.04**: Feedback correlates to game/session/turn identifiers.
- [ ] **AC-68.05**: Client ships inside the existing API deployment surface.
- [ ] **AC-68.06**: Invalid invite/access states fail clearly.
- [ ] **AC-68.07**: Thinking/streaming/reconnecting state appears within 500 ms.

## 8. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|---|---|---|
| S10 | Streaming API | Client consumes existing SSE events and reconnect semantics. |
| S11 | Sessions | Client displays/reuses session identity without requiring v3 accounts. |
| S27 | Save/load | Client exposes basic save/load affordances using existing game-management APIs. |
| S42-S45 | Evaluation | Human feedback becomes evaluation input but does not replace automated scoring. |
| S69 | Choices/systems | Choice buttons may represent system-generated options but remain ordinary turn inputs. |
| S70 | Map/travel | v3 map panel can attach to reserved client state seams. |

## 9. Open Questions

1. Should invite-link validation be enforced server-side before serving the client shell, or only before game/session API calls? — *Impact: moderate* — *Owner: implementation plan*
2. Should the v2.1 client support mobile layout, or only desktop playtesting? — *Impact: moderate* — *Owner: product review*

## 10. Out of Scope

- Full account creation, OAuth, profiles, or player dashboard — v3/v4 Player Experience work.
- Full character sheet, inventory, and graphical map panels — v3 client expansion.
- React/Svelte migration — only adopted after v3 architecture review trigger.
- Community story sharing or public gallery features — Sharing/Social component.
- Voice input/output and mobile app packaging — v4+ UI/accessibility work.
