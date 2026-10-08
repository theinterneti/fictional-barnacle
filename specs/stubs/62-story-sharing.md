# S62 — Story Sharing

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v5+
> **Implementation Fit**: ❌ Not Started
> **Level**: 1 — Core Game
> **Dependencies**: S37 (Memory Records), S17 (Privacy and Data Retention), S27 (Save/Load and Game Management)
> **Related**: S61 (Therapeutic Framework annotations), S48 (Async Job Runner for export)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

S62 enables players to export their TTA stories — the narrative journey of a
completed game — in human-readable formats for personal keeping, sharing, or
reflection.

Stories are derived from **MemoryRecords** (S37), not raw turn transcripts.
This ensures exports are curated, meaningful narratives rather than verbose
logs. It also respects S17 privacy requirements: PII that is not part of the
narrative is never included in exports.

---

## 2. Export Formats

| Format | Description | Use case |
|---|---|---|
| **PDF** | Formatted narrative document with title, chapter structure, cover art prompt | Personal archive, printing |
| **ePub** | E-reader compatible format | Reading on Kindle/Kobo |
| **Web (HTML)** | Shareable URL to a read-only hosted story page | Social sharing |

PDF and ePub are generated as downloadable files. Web format is a hosted page
at `app.tta.io/stories/{story_id}` (public URL; unlisted by default).

---

## 3. Story Structure

The export pipeline constructs a story document from:

1. **Act structure**: MemoryRecords grouped by story arc phase (S05)
   into chapters (Opening, Rising Action, Climax, Resolution)
2. **Scene summaries**: each chapter contains the MemoryRecords from that
   phase, condensed into prose by a dedicated LLM summarization call
3. **Character portrait**: a brief description of the actor's character
   derived from their identity attributes (S31) and echo memories
4. **World colophon**: a short description of the universe the story took place in
5. **Therapeutic annotations** (optional, if S61 enabled and player opts in):
   a short reflection section at the end, drawn from `therapeutic_technique`
   annotations (S61 FR-61.02)

---

## 4. Privacy Safeguards

- Exports MUST NOT include raw player inputs (only the MemoryRecord-derived narrative)
- Exports MUST NOT include session IDs, player IDs, or account information
- Web stories are unlisted (not indexed) by default; player must opt-in to public indexing
- Exports are subject to retention policy: web story URLs expire after
  `story_url_retention_days` (default: 365) unless renewed
- On GDPR deletion (S17), all exports and web story URLs are deleted

---

## 5. Functional Requirements

### FR-62.01 — Export Request

A player may request an export of a completed game via `POST /api/v1/games/{game_id}/export`
with `{format: "pdf" | "epub" | "web"}`. The request is enqueued as an ARQ job
(S48). A `202 Accepted` response with a `job_id` is returned immediately.

### FR-62.02 — Story Assembly

The ARQ job runs the story assembly pipeline: MemoryRecord retrieval →
arc grouping → LLM summarization → format rendering. Total pipeline target:
≤ 60 seconds for a standard-length game (25 turns).

### FR-62.03 — Download / URL Delivery

On job completion, the player receives:
- For PDF/ePub: a signed S3 URL valid for 24 hours
- For web: the permanent (until expiry) story URL

### FR-62.04 — Source as MemoryRecords

Export content is derived exclusively from MemoryRecords with `importance_score ≥ 0.5`.
Raw turn transcripts are never used as export source material.

### FR-62.05 — Game Must Be Completed

Export is only available for games in `completed` or `abandoned` state.
In-progress games cannot be exported.

---

## 6. Acceptance Criteria (Gherkin)

```gherkin
Feature: Story Sharing

  Scenario: AC-62.01 — Export request returns 202 with job_id
    Given a player with a completed game
    When POST /api/v1/games/{game_id}/export {format: pdf} is called
    Then a 202 response is returned with a job_id
    And an ARQ job is enqueued

  Scenario: AC-62.02 — PDF export completes within 60 seconds
    Given a standard 25-turn game
    When the export ARQ job runs
    Then a signed S3 URL is produced within 60 seconds

  Scenario: AC-62.03 — Web story URL uses unguessable token and is unlisted by default
    Given a web export is completed
    When the story URL is generated
    Then the story_id embedded in the URL is a high-entropy, unguessable UUID (not sequential)
    And the URL is not indexed by search engines (noindex header)
    And viewer authentication is not required when the request carries a valid story_id
    And requests that omit a valid story_id return a 404 response

  Scenario: AC-62.04 — GDPR deletion removes all exports
    Given a player with an exported story
    When a GDPR deletion request is processed (S17)
    Then the story file and web URL are deleted
```

---

## 7. Out of Scope

- Social feed or discovery (S63).
- Export of in-progress games.
- Video or audio formats.

---

## 8. Open Questions

| ID | Question | Status |
|---|----------|--------|
| OQ-62.01 | Which S3-compatible storage provider? | 🔓 Open — Fly.io Tigris is the likely choice (already on Fly.io per S46). |
| OQ-62.02 | What PDF rendering library? | 🔓 Open — WeasyPrint (CSS-based, Python) or Reportlab; deferred to v5 impl. |
