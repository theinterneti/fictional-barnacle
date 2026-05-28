# S43 — Human Playtester Program

> **Status**: ✅ Approved
> **Release Baseline**: 🆕 v2.1
> **Implementation Fit**: ❌ Not Started
> **Level**: 4 — Operations
> **Dependencies**: S41 (Scenario Seed Library)
> **Related**: S42 (LLM Playtester), S44 (Narrative Quality Evaluation), S17 (Privacy)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

LLM playtesters (S42) catch structural and coherence failures. They do not
feel. They do not get bored. They do not experience a moment of wonder, or
notice that the pacing dragged through Act IV, or feel uncomfortable about
the way a consequence was framed.

S43 defines the human playtester program: a small-scale (10–30 participants)
structured feedback process where real humans play curated scenarios and
report their experience through a standardized intake form. S43 satisfies the
*sufficient* half of v2.1 validation that the v1 project charter explicitly
called out: automated testing is necessary but not sufficient.

S43 covers:
- Recruitment criteria and process
- Consent, compensation, and privacy policy
- Session structure (what playtesters do, how long)
- Feedback intake form format
- Triage pipeline: how feedback becomes regression tickets
- Roles and responsibilities

---

## 2. Scope and Scale

**v2.1 target**: 10–30 playtesters. This is deliberately small. The goal is
signal quality, not statistical volume. A 100-person study is out of scope
for v2.1; that belongs to a future marketing/product research phase.

**Session structure**: Each participant plays one curated scenario (S41) to
completion (Genesis + at least 5 gameplay turns). One session per participant
per scenario. A participant may play multiple scenarios across multiple sessions.

**Compensation**: Nominal gift card (value TBD by ops team; ~$15–25 USD
equivalent). Participation is voluntary and participants may stop at any time.

---

## 3. Roles

| Role | Responsibilities |
|------|-----------------|
| **Program Coordinator** | Recruits playtesters, schedules sessions, distributes access tokens, handles consent forms |
| **Playtester** | Plays a scenario; completes the feedback form |
| **Triage Reviewer** | Reviews submitted feedback; creates regression tickets; marks low-signal entries |
| **Narrative Designer** | Reviews regression tickets flagged as narrative issues; proposes fixes |

---

## 4. Recruitment

### 4.1 Criteria

Participants MUST:
- Be 18 years of age or older
- Be able to read and write in English
- Have at least occasional familiarity with interactive fiction, text games,
  or narrative games (examples provided; no prior TTA experience required)

Participants MUST NOT:
- Be current employees or contractors of the TTA project
- Have contributed code, specs, or design to TTA in the prior 6 months

### 4.2 Recruitment Channels

v2.1 channels (in priority order):
1. Direct invite: known friends and community members of the team
2. Interactive fiction community forums (e.g., IF Forum, IFDB community)
3. General social post targeting narrative game enthusiasts

Participants are NOT recruited from general public labor platforms (e.g.,
Mechanical Turk) for v2.1. Engagement quality is prioritized over throughput.

### 4.3 Access Provisioning

Each participant receives a single-use access token scoped to their assigned
scenario seed. Tokens expire 7 days after issuance. Token management is a
manual ops task for v2.1 (no automated provisioning).

---

## 5. Consent and Privacy

### 5.1 Consent Form

Before accessing TTA, each participant MUST complete a digital consent form that:
- Describes TTA and the purpose of the playtester program
- States that their session transcript will be stored and reviewed by the TTA team
- States that feedback will be used to improve the system
- Confirms compensation amount and terms
- Includes an opt-out clause (participant may withdraw at any time; stored
  data is deleted within 14 days of withdrawal request)

Consent form MUST comply with v1 S17 (Privacy) consent requirements.

### 5.2 Data Retention

Playtester session transcripts are retained for a maximum of 90 days after
the v2.1 evaluation window closes. After 90 days they are deleted.
Feedback form responses (anonymized) may be retained indefinitely for
longitudinal tracking.

### 5.3 Anonymization

Feedback form responses are anonymized before sharing with the narrative
design team: participant names and contact details are stripped. Session
transcripts are tagged by session ID only.

---

## 6. Session Structure

A standard playtester session:

| Step | Duration | Description |
|------|----------|-------------|
| 1. Onboarding | 5 min | Read a one-page orientation guide (no spoilers about TTA mechanics) |
| 2. Play | 20–40 min | Play the assigned scenario through Genesis + 5+ gameplay turns |
| 3. Feedback form | 10–15 min | Complete the structured feedback intake form |
| **Total** | **35–60 min** | |

Participants are free to exceed 5 turns if they wish to continue. The form
is submitted before they close the browser. Sessions are not timed.

---

## 7. Feedback Intake Form

The feedback intake form is a structured digital form (Google Forms or equivalent).
It produces a JSON record for each submission.

### 7.1 Quantitative Fields

| Field ID | Question | Scale |
|----------|----------|-------|
| `q_coherence` | "The story made sense from moment to moment" | 1–5 |
| `q_wonder` | "At least once, I felt surprised or delighted by the narrative" | 1–5 |
| `q_character` | "My character felt like mine — shaped by my choices" | 1–5 |
| `q_pacing` | "The story moved at a pace that felt right" | 1–5 |
| `q_genesis_comfort` | "Getting started felt natural, not overwhelming" | 1–5 |
| `q_consequence` | "My choices seemed to matter to the story" | 1–5 |
| `q_overall` | "Overall, I enjoyed this experience" | 1–5 |
| `q_recommend` | "I would recommend this to a friend" | Yes / No / Maybe |

### 7.2 Qualitative Fields

| Field ID | Question | Type |
|----------|----------|------|
| `q_best_moment` | "Describe one moment that worked really well." | Free text (≤ 500 chars) |
| `q_worst_moment` | "Describe one moment that didn't work for you." | Free text (≤ 500 chars) |
| `q_confusion` | "Was there anything confusing or unclear?" | Free text (≤ 500 chars) |
| `q_freeform` | "Any other thoughts?" | Free text (≤ 500 chars) |

### 7.3 Metadata Fields (Auto-populated)

| Field | Source |
|-------|--------|
| `session_id` | Provided by access token |
| `scenario_seed_id` | Derived from session |
| `turns_played` | API-reported turn count |
| `genesis_completed` | Boolean from session state |
| `submission_timestamp` | Form submit time |

---

## 8. Triage Pipeline

After the evaluation window closes, a Triage Reviewer processes all submissions:

1. **Score baseline**: Compute median and distribution for each quantitative
   field. Any field with median < 3.0 is flagged as a **regression candidate**.
2. **Qualitative review**: Read all `q_worst_moment` and `q_confusion` entries.
   Group by theme (pacing, Genesis confusion, consequence gap, prose tone).
3. **Regression ticket creation**: For each flagged issue, create a GitHub issue
   with label `playtester-regression` and the scenario seed ID.
   Ticket includes: raw quotes (anonymized), quantitative score context,
   suggested spec section (e.g., "S40 Phase 3", "S44 coherence metric").
4. **Low-signal marking**: Submissions with `q_overall == 1` AND all fields == 1
   with no qualitative content are flagged as low-signal and excluded from
   aggregate scoring.

### 8.1 Escalation Threshold

If median `q_overall` < 3.0 across the cohort, or median `q_coherence` < 3.0,
the evaluation pipeline (S45) MUST mark the release as **NOT VALIDATED** and
block the v2.1 milestone tag.

---

## 9. Acceptance Criteria

```gherkin
Feature: Human Playtester Program

  Scenario: AC-43.01 — Consent collected before session access
    Given a participant has a valid access token
    When they attempt to access TTA without completing the consent form
    Then they are redirected to the consent form
    And session access is not granted until consent is recorded

  Scenario: AC-43.02 — Feedback form produces structured JSON record
    Given a participant completes the feedback form
    When the form is submitted
    Then a JSON record with all required fields is stored
    And session_id, scenario_seed_id, and submission_timestamp are auto-populated

  Scenario: AC-43.03 — Participant withdrawal triggers data deletion
    Given a participant requests withdrawal
    When the request is processed
    Then their session transcript is deleted within 14 days
    And their feedback record is anonymized (name and contact stripped)

  Scenario: AC-43.04 — Low median triggers NOT VALIDATED signal
    Given the cohort median for q_overall is 2.5
    When the triage reviewer runs the aggregate scoring
    Then the evaluation pipeline receives a NOT_VALIDATED signal
    And a regression ticket is created with all below-threshold scores
```

---

## 10. Out of Scope

- Automated participant recruitment or scheduling (manual ops for v2.1).
- Longitudinal tracking of the same participants across releases (v3+).
- A/B testing of narrative variants with participant cohorts.
- Therapeutic impact evaluation — S18 (future stub).
- NDA requirement for participants (not warranted at v2.1 scale).

---

## 11. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-43.01 | Recruitment channels and compensation level | ✅ Resolved | Channels: direct invite → IF forums → general social. Compensation: ~$15–25 gift card (exact amount set by ops). No Mechanical Turk for v2.1. |
| OQ-43.02 | NDA / consent form legal review | ⚠️ Open | Consent form template provided in this spec; legal review required before first participant is recruited. |
| OQ-43.03 | Feedback form platform | ✅ Resolved | Google Forms or equivalent. Must produce structured JSON-exportable records. Exact platform is an ops decision. |
