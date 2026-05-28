# S63 — Community and User-Generated Worlds

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v5+
> **Implementation Fit**: ❌ Not Started
> **Level**: 1 — Core Game
> **Dependencies**: S41 (Scenario Seed Library), S39 (Universe Composition Model), S24 (Content Moderation), S17 (Privacy)
> **Related**: S62 (Story Sharing), S48 (Async Job Runner for moderation)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

S63 enables players and designers to author, share, and play community-created
world templates. It extends the S39/S41 template system to include a submission,
moderation, and discovery pipeline.

The primary use cases are:
1. **Creator**: a player authors a world template and publishes it
2. **Explorer**: a player discovers and starts a game in a community-created world
3. **Moderator**: an admin reviews and approves/rejects submissions

---

## 2. Template Authoring

Community templates use the same S39 universe composition schema as built-in
templates. A web-based template editor (not in scope for v5 engine spec;
UI design is deferred) allows creators to define:
- Universe composition (genre, themes, reality_coherence, etc.)
- Scenario seeds (S41 format)
- NPC archetypes
- Location definitions
- Nexus ritual (optional, S53)

Templates are submitted as YAML blobs via `POST /community/templates`.

---

## 3. Moderation Pipeline

Submitted templates are NOT immediately published. They enter a moderation queue:

```
status:pending → (automated review) → status:approved
                                    → status:pending_human_review → (admin decision) → status:approved / status:rejected
```

**Automated review**: an LLM moderation call (S24) evaluates the template YAML
for prohibited content (S24 categories), policy violations, and safety concerns.
Templates with no flags are auto-approved. Templates with flags enter human review.

**Human review**: an admin uses the `GET /admin/community/templates/pending` queue
and `POST /admin/community/templates/{id}/decision` endpoint.

---

## 4. Functional Requirements

### FR-63.01 — Template Submission

`POST /community/templates` accepts a template YAML payload. On submission:
- Template is validated against the S39 schema
- A `community_template_id` is assigned
- An ARQ job (S48) is enqueued for automated review
- A `201 Created` response is returned with `community_template_id` and `status: pending`

### FR-63.02 — Automated Review

The ARQ job runs S24 moderation on the template content. If the template
passes, `status` is set to `approved` and the template is discoverable.
If flags are detected, `status` is set to `pending_human_review`.

### FR-63.03 — Template Discovery

`GET /community/templates` returns approved templates with pagination, filtering
by genre/theme, and sorted by `play_count desc` (most-played first).

### FR-63.04 — Starting a Community Game

A player starts a game using a community template via the standard
`POST /api/v1/games` endpoint with a `template_id` pointing to the community
template. The game instantiation pipeline (S02/S03 Genesis) is unchanged.

### FR-63.05 — Attribution

Community templates include a `creator_display_name` field (not player ID).
Attribution is shown on the template discovery page and game genesis.
Creator identity is pseudonymous; real identity is not exposed.

### FR-63.06 — Template Versioning

Templates are immutable once approved. A creator may submit a new version,
which enters the moderation queue independently. Existing games using
an older version continue on that version.

### FR-63.07 — Takedown

Admins may unpublish a template at any time. Unpublished templates are hidden
from discovery; existing games using the template are unaffected.

---

## 5. Acceptance Criteria (Gherkin)

```gherkin
Feature: Community and User-Generated Worlds

  Scenario: AC-63.01 — Template submission creates pending record
    Given a valid S39 template YAML
    When POST /community/templates is called
    Then a 201 response is returned with community_template_id
    And the template has status = pending
    And an ARQ review job is enqueued

  Scenario: AC-63.02 — Clean template is auto-approved
    Given a template with no moderation flags
    When the ARQ review job runs
    Then the template status is set to approved
    And it appears in GET /community/templates

  Scenario: AC-63.03 — Flagged template enters human review
    Given a template with a content flag from S24
    When the ARQ review job runs
    Then the template status is set to pending_human_review
    And it appears in GET /admin/community/templates/pending

  Scenario: AC-63.04 — Player can start a game with community template
    Given an approved community template
    When POST /api/v1/games {template_id: community_template_id} is called
    Then a game is instantiated using that template
    And the genesis pipeline runs normally
```

---

## 6. Out of Scope

- Template editor UI (deferred to v5 UX design).
- Collaborative template authoring (single creator per template in v5).
- Revenue sharing or monetization.
- Template comments or ratings (v6+ community features).

---

## 7. Open Questions

| ID | Question | Status |
|---|----------|--------|
| OQ-63.01 | Should community templates be sandboxed from core templates? | 🔓 Open — yes, a `source: community` field separates them; same engine, different discovery path. |
| OQ-63.02 | What is the SLA for human review turnaround? | 🔓 Open — 48-hour target for v5 launch; depends on moderation staffing. |
