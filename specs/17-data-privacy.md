# S17 — Data Privacy

> **Status**: 📝 Draft
> **Level**: 4 — Operations
> **Dependencies**: S01 (Gameplay Loop), S05 (Choice & Consequence), S14 (Deployment), S15 (Observability)
> **Last Updated**: 2026-04-07

## Overview

This spec defines what data TTA collects, how it is stored, who has access, and what rights players have over their data. It is honest about v1 limitations: TTA is **not HIPAA-compliant**, does share player input with third-party LLM providers, and has a basic (not enterprise-grade) approach to data protection.

The guiding principle is **informed consent**: players should know exactly what happens to their data before they play. No surprises.

### Out of Scope

- **HIPAA compliance** — TTA is a game, not a healthcare service — explicitly disclaimed in §8
- **SOC 2 / ISO 27001 certification** — OSS project, not an enterprise vendor — future if commercialized
- **Data Protection Officer (DPO) appointment** — not required for OSS v1 at current scale — GDPR Art. 37
- **Cookie consent banners** — v1 uses session cookies only, no third-party tracking — §12 (Privacy Policy)
- **International data transfer mechanisms (SCCs, adequacy decisions)** — self-hosted v1, no cross-border transfer by default — future if multi-region
- **Automated PII detection / DLP tooling** — manual classification for v1 — future enhancement

---

## 1. Data Inventory

### 1.1 User Stories

- **US-17.1**: As a player, I can understand what data TTA collects about me before I create an account.
- **US-17.2**: As a developer, I can look up exactly what data is stored where for any data category.

### 1.2 Functional Requirements

**FR-17.1**: TTA SHALL collect and store the following data:

#### Player Profile Data

| Field | Classification | Storage | Retention |
|-------|---------------|---------|-----------|
| Player ID | Pseudonymous identifier | PostgreSQL | Account lifetime |
| Display name | PII (optional, player-chosen) | PostgreSQL | Account lifetime |
| Email address | PII (if used for auth) | PostgreSQL | Account lifetime |
| Password hash | Authentication credential | PostgreSQL | Account lifetime |
| Account creation date | Metadata | PostgreSQL | Account lifetime |
| Last login date | Metadata | PostgreSQL | Account lifetime |
| Consent records | Legal | PostgreSQL | Permanent (legal requirement) |

#### Game State Data

| Field | Classification | Storage | Retention |
|-------|---------------|---------|-----------|
| Current world state | Game data | Neo4j | Session lifetime + 30 days |
| Narrative history | Game data (may contain personal input) | Neo4j | Session lifetime + 30 days |
| Player choices | Game data | Neo4j | Session lifetime + 30 days |
| Session metadata | System data | Redis (live), PostgreSQL (archived) | Redis: 24h TTL, PostgreSQL: 90 days |
| Game progress/achievements | Game data | PostgreSQL | Account lifetime |

#### LLM Interaction Data

| Field | Classification | Storage | Retention |
|-------|---------------|---------|-----------|
| Player input text | PII (may contain personal disclosures) | Langfuse, LLM provider (transient) | Langfuse: 90 days |
| System prompts | System data | Langfuse | 90 days |
| LLM responses | Generated content | Langfuse | 90 days |
| Token counts | System metrics | Langfuse, Prometheus | Langfuse: 90 days, Prometheus: 30 days |
| Model used | System metadata | Langfuse, logs | 90 days |

#### System/Operational Data

| Field | Classification | Storage | Retention |
|-------|---------------|---------|-----------|
| Application logs | System data (no PII per S15) | Stdout/log aggregator | 30 days |
| Metrics | System data | Prometheus | 30 days |
| Traces | System data (no PII per S15) | Jaeger/Tempo | 7 days |
| Error reports | System data | Logs | 30 days |

**FR-17.2**: The data inventory above SHALL be maintained as a living document. Any new data collection SHALL be added to the inventory before implementation.

### 1.3 Acceptance Criteria

- [ ] Every data field stored by TTA is documented in the data inventory.
- [ ] Every field has a classification, storage location, and retention period.
- [ ] No data is collected that is not in the inventory.

---

## 2. Data Classification

### 2.1 Functional Requirements

**FR-17.3**: All data SHALL be classified into one of four categories:

| Classification | Description | Examples | Handling |
|---------------|-------------|----------|----------|
| **PII** | Personally identifiable information | Email, display name, IP address | Encrypted at rest, access-logged, erasable on request |
| **Sensitive Game Data** | Game content that may reveal personal information | Player input text, narrative choices about personal topics | Pseudonymized, erasable on request, shared with LLM provider (disclosed) |
| **Game Data** | Non-sensitive game state | World state, NPC positions, inventory | Standard protection, erasable on request |
| **System Data** | Operational data with no personal content | Metrics, logs (PII-scrubbed), traces | Standard protection, retained per operational need |

**FR-17.4**: Player input text is classified as **Sensitive Game Data** because:
- Players may disclose personal experiences, feelings, or situations during gameplay.
- TTA's therapeutic framing may encourage deeper personal sharing than a typical game.
- This data is sent to third-party LLM providers for processing.

**FR-17.5**: The classification of each data field SHALL be enforced programmatically where possible. PII fields SHALL be marked in the database schema (column comments or ORM metadata).

### 2.2 Acceptance Criteria

- [ ] Every data field has exactly one classification.
- [ ] PII fields are identifiable in the database schema.
- [ ] Code review checklist includes data classification review for new fields.

---

## 3. GDPR Compliance

### 3.1 User Stories

- **US-17.3**: As a player, I can request a copy of all data TTA has about me.
- **US-17.4**: As a player, I can request deletion of all my data and TTA will comply.
- **US-17.5**: As a player, I can export my game data in a standard format.

### 3.2 Functional Requirements

#### Right to Access (Article 15)

**FR-17.6**: Players SHALL be able to request a copy of all their personal data. The system SHALL provide an API endpoint:

```
GET /api/player/me/data-export
```

Response: a JSON file containing:
- Player profile data
- Game session history (all sessions)
- Player input history (all turns)
- Consent records
- Data processing log (what was shared with LLM providers)

**FR-17.7**: Data export SHALL be generated asynchronously. The player receives a download link (valid for 24 hours) when the export is ready.

**FR-17.8**: Data export SHALL be completed within 72 hours of request. For v1, this is a manual process triggered by the API endpoint but may require operator involvement for Langfuse data.

#### Right to Erasure (Article 17)

**FR-17.9**: Players SHALL be able to request deletion of all their data:

```
DELETE /api/player/me
```

**FR-17.10**: Upon erasure request, the system SHALL:
1. Delete the player profile from PostgreSQL.
2. Delete all session data from PostgreSQL.
3. Delete all game state from Neo4j (player node and all connected nodes).
4. Delete cached session data from Redis.
5. Submit a Langfuse data deletion request for the player's pseudonymized ID.
6. Log the deletion request and completion (the log itself does not contain deleted data).

**FR-17.11**: Erasure timelines are tiered by data location:
- **TTA-controlled data** (PostgreSQL, Neo4j, Redis) SHALL be erased within
  **72 hours**, consistent with S11 FR-11.62.
- **Third-party observability data** (Langfuse traces and spans) SHALL be erased
  within **30 days**, as deletion requires an API request to an external service
  and may involve manual operator verification.
- The player SHALL receive immediate confirmation that the deletion request was
  accepted, and a final confirmation when all erasure (including third-party) is
  complete.

**FR-17.12**: Some data MAY be retained after erasure if legally required:
- Consent records (proof that consent was given/withdrawn).
- The fact that an account existed and was deleted (audit trail).
- Anonymized, aggregated analytics (see Section 10).

#### Right to Portability (Article 20)

**FR-17.13**: The data export format (FR-17.6) SHALL use a standard, machine-readable format (JSON). This satisfies portability.

### 3.3 Edge Cases

- **EC-17.1**: If a player requests erasure during an active session, the session SHALL be terminated and then erased.
- **EC-17.2**: If Langfuse data deletion fails (API error), the system SHALL retry and log the failure. An operator SHALL be alerted if deletion cannot be completed within 30 days.
- **EC-17.3**: If a player requests data export and then requests erasure before the export is generated, the export SHALL be cancelled and erasure takes priority.

### 3.4 Acceptance Criteria

- [ ] `GET /api/player/me/data-export` returns all player data in JSON format.
- [ ] `DELETE /api/player/me` removes all player data from all storage systems.
- [ ] After erasure, no query to any database returns data for the deleted player.
- [ ] Consent records are preserved after erasure (anonymized).

---

## 4. Data Retention

### 4.1 Functional Requirements

**FR-17.14**: Data retention periods SHALL be:

| Data Category | Retention Period | Justification |
|---------------|-----------------|---------------|
| Active session data (Redis) | 24 hours from last activity | Sessions are ephemeral; inactive sessions expire |
| Completed session data (PostgreSQL) | 90 days from session end | Allows players to review recent games |
| Player profile | Until account deletion | Players control their account lifetime |
| LLM interaction data (Langfuse) | 90 days | Needed for quality improvement and debugging |
| Application logs | 30 days | Operational troubleshooting |
| Metrics | 30 days | Trend analysis |
| Traces | 7 days | Short-term debugging |
| Consent records | Permanent | Legal requirement |

**FR-17.15**: Expired data SHALL be automatically purged by a scheduled job. The purge job SHALL:
- Run daily.
- Log how many records were purged per category.
- Not impact application performance (run during low-traffic hours or use batch deletes).

**FR-17.16**: Players SHALL be informed of retention periods in the privacy policy.

### 4.2 Acceptance Criteria

- [ ] Session data older than 90 days is automatically purged.
- [ ] Langfuse data older than 90 days is automatically purged.
- [ ] Purge job logs its activity.
- [ ] Purge job does not cause noticeable performance degradation.

---

## 5. Encryption

### 5.1 Functional Requirements

#### In Transit

**FR-17.17**: All client-to-server communication SHALL use TLS 1.2 or higher. In v1 (Docker Compose), this means:
- A reverse proxy (Nginx, Caddy) terminates TLS in staging.
- Local development MAY use plain HTTP (localhost only).
- API-to-database communication within the Docker network is unencrypted (acceptable for v1, same-host).

**FR-17.18**: All communication with external services (LLM APIs, Langfuse) SHALL use HTTPS.

#### At Rest

**FR-17.19**: For v1, encryption at rest is handled at the infrastructure level:
- PostgreSQL: rely on volume encryption if the host supports it (documented, not enforced by the application).
- Neo4j: same as PostgreSQL.
- Redis: data is ephemeral (24h TTL) and not persisted to disk in v1.

**FR-17.20**: Sensitive fields that warrant application-level encryption in future versions:
- Player email addresses.
- Authentication tokens.
- This is documented as a v2 requirement, not implemented in v1.

**FR-17.21**: Password hashes SHALL use bcrypt (or argon2id) with a minimum cost factor of 12. Passwords SHALL NOT be stored in plaintext under any circumstances.

### 5.2 Acceptance Criteria

- [ ] Staging deployment uses TLS for all client-facing traffic.
- [ ] All LLM API calls use HTTPS.
- [ ] Passwords are stored as bcrypt/argon2id hashes, never plaintext.
- [ ] Documentation states that v1 does not implement application-level encryption at rest.

---

## 6. Consent

### 6.1 User Stories

- **US-17.6**: As a player, I am clearly informed about what data is collected before I start playing.
- **US-17.7**: As a player, I can withdraw my consent and stop data collection.
- **US-17.8**: As a player, I understand that my game input is sent to third-party AI services.

### 6.2 Functional Requirements

**FR-17.22**: Before creating an account, the player SHALL be presented with a consent prompt that clearly states:

1. **What data is collected**: Player profile, game interactions, choices.
2. **How data is used**: To generate narrative responses, improve game quality, track game state.
3. **Who sees the data**: TTA operators and third-party LLM providers (named — e.g., "OpenAI" or "Anthropic").
4. **How long data is kept**: Retention periods per category.
5. **Player rights**: Access, erasure, portability.
6. **NOT therapy**: TTA is a game with therapeutic elements, not a substitute for professional mental health care. Player data is NOT protected by therapist-patient privilege.

**FR-17.23**: Consent SHALL be recorded with:
- Timestamp of consent.
- Version of the privacy policy consented to.
- IP address (hashed) at time of consent.
- Specific consent categories accepted/declined.

**FR-17.24**: Consent categories:

| Category | Required? | Description |
|----------|-----------|-------------|
| Core gameplay | Required | Data processing needed to play the game |
| LLM processing | Required | Sending input to LLM providers for response generation |
| Quality improvement | Optional | Using interaction data to improve prompts and game quality |
| Analytics | Optional | Anonymized usage analytics |

**FR-17.25**: If a player declines a required consent category, they SHALL NOT be able to create an account or play. The system SHALL clearly explain why.

**FR-17.26**: Players SHALL be able to update their consent preferences at any time via settings. Withdrawing optional consent SHALL take effect within 24 hours.

### 6.3 Edge Cases

- **EC-17.4**: If the privacy policy is updated, existing players SHALL be notified and asked to review and accept the updated policy on their next login.
- **EC-17.5**: If a player withdraws "Quality improvement" consent, their data SHALL no longer be used for quality analysis, but existing analysis results are not retroactively removed.

### 6.4 Acceptance Criteria

- [ ] A new player sees the consent prompt before any data is collected.
- [ ] Consent records include timestamp and policy version.
- [ ] Declining required consent prevents account creation with a clear explanation.
- [ ] Players can view and update consent preferences in settings.

---

## 7. Third-Party Data Sharing

### 7.1 User Stories

- **US-17.9**: As a player, I know exactly which company processes my game input.
- **US-17.10**: As a player, I understand that my input may be used by the LLM provider according to their policies.

### 7.2 Functional Requirements

**FR-17.27**: TTA SHALL disclose all third-party services that receive player data:

| Third Party | Data Shared | Purpose | Retention by Third Party |
|-------------|-------------|---------|--------------------------|
| LLM Provider (e.g., OpenAI, Anthropic) | Player input text, system prompts | Generating narrative responses | Per provider's data policy |
| Langfuse (if cloud-hosted) | Full prompts and completions, pseudonymized player ID | LLM observability | 90 days (configurable) |

**FR-17.28**: The privacy policy SHALL link to each third-party provider's data processing policy.

**FR-17.29**: TTA SHALL use LLM provider API configurations that minimize data retention by the provider:
- Use API endpoints that do not train on user data (e.g., OpenAI's API data usage policy).
- Do NOT use free-tier endpoints that may use data for training.
- Document which provider configuration is used and why.

**FR-17.30**: If the LLM provider changes, the privacy policy SHALL be updated and players notified.

**FR-17.31**: Self-hosted Langfuse is preferred over cloud-hosted for v1 to keep LLM interaction data under operator control.

### 7.3 Acceptance Criteria

- [ ] Privacy policy names all third-party data processors.
- [ ] Privacy policy links to each processor's data policy.
- [ ] LLM API configuration does not opt into data training.
- [ ] Changing the LLM provider triggers a privacy policy update.

---

## 8. NOT HIPAA-Compliant

### 8.1 Functional Requirements

**FR-17.32**: TTA v1 is explicitly **NOT HIPAA-compliant**. This SHALL be clearly stated in:
- The privacy policy.
- The terms of service.
- The README.
- The onboarding consent flow.

**FR-17.33**: The reasons TTA is not HIPAA-compliant:

| HIPAA Requirement | TTA v1 Status | Why |
|-------------------|---------------|-----|
| Business Associate Agreements (BAAs) | Not in place | LLM providers don't have BAAs with TTA |
| Audit controls | Basic | Logging exists but doesn't meet HIPAA audit standards |
| Access controls | Basic | No role-based access beyond admin/player |
| Encryption at rest | Infrastructure-dependent | Not enforced at the application level |
| Data breach notification | Basic plan exists | Not compliant with HIPAA's 60-day notification requirement |
| Designated privacy officer | No | OSS project, no dedicated privacy officer |
| Workforce training | No | OSS contributors, not employed workforce |

**FR-17.34**: TTA SHALL NOT market itself as a medical device, therapy tool, or health care service. Marketing language SHALL use terms like "game with therapeutic elements" or "narrative experience for self-reflection," not "therapy" or "treatment."

**FR-17.35**: The application SHALL include a disclaimer visible during gameplay:
> "TTA is a narrative game, not a substitute for professional mental health care. If you are in crisis, please contact [crisis hotline resource]."

### 8.2 Acceptance Criteria

- [ ] README contains a clear "Not HIPAA-compliant" statement.
- [ ] Consent flow includes the non-HIPAA disclosure.
- [ ] In-game disclaimer is visible during gameplay.
- [ ] No marketing material uses the words "therapy," "treatment," or "medical."

---

## 9. Children & Age Restrictions

### 9.1 Functional Requirements

**FR-17.36**: TTA v1 SHALL restrict access to users aged 13 and older. This is a COPPA boundary — under 13 requires verifiable parental consent, which TTA does not implement.

**FR-17.37**: The account creation flow SHALL include an age confirmation:
- "I confirm that I am 13 years of age or older."
- This is a self-declaration, not age verification (no ID check in v1).

**FR-17.38**: If age verification is not confirmed, account creation SHALL be denied.

**FR-17.39**: TTA SHALL NOT knowingly collect data from children under 13. If an operator discovers that data belongs to a child under 13, that data SHALL be deleted immediately.

**FR-17.40**: For future versions, the age restriction MAY be raised to 16 (GDPR's default in some EU member states) or 18 depending on the therapeutic content intensity.

### 9.2 Acceptance Criteria

- [ ] Account creation requires age confirmation (13+).
- [ ] Declining age confirmation prevents account creation.
- [ ] Privacy policy states the minimum age requirement.

---

## 10. Data Anonymization

### 10.1 User Stories

- **US-17.11**: As a developer, I can analyze gameplay patterns without accessing individual player data.
- **US-17.12**: As a researcher (future), I can study anonymized gameplay data for therapeutic effectiveness.

### 10.2 Functional Requirements

**FR-17.41**: TTA SHALL support anonymization of game data for analytics purposes:
- Replace player IDs with random identifiers.
- Remove display names and email addresses.
- Generalize timestamps to daily granularity.
- Remove or generalize any player-input text that contains PII.

**FR-17.42**: Anonymized datasets SHALL be clearly marked as anonymized and stored separately from live data.

**FR-17.43**: Anonymization SHALL be irreversible. There SHALL be no mapping table from anonymized IDs back to real player IDs.

**FR-17.44**: For v1, anonymization is a manual, operator-initiated process. Automated anonymization pipelines are a future enhancement.

**FR-17.45**: Anonymized data MAY be retained indefinitely (it is no longer personal data under GDPR).

### 10.3 Acceptance Criteria

- [ ] An anonymization script exists that processes a data export into anonymized form.
- [ ] Anonymized data cannot be traced back to a specific player.
- [ ] Anonymized datasets contain no PII.
- [ ] Anonymization is irreversible (no reverse mapping).

---

## 11. Data Breach Response

### 11.1 Functional Requirements

**FR-17.46**: TTA SHALL have a basic data breach response plan:

#### Detection

**FR-17.47**: Signs of a potential breach:
- Unauthorized access to databases (unusual query patterns).
- Exposed environment variables or secrets in logs/public repos.
- Player reports of unauthorized account access.
- Unexpected data exports or bulk queries.

#### Response

**FR-17.48**: Upon detecting a potential breach:
1. **Contain** (within 1 hour): Revoke compromised credentials, rotate API keys, disable affected endpoints.
2. **Assess** (within 24 hours): Determine what data was exposed, how many players affected, attack vector.
3. **Notify** (within 72 hours of confirmation): Inform affected players via email. Post a public notice. For GDPR: notify supervisory authority if applicable.
4. **Remediate** (within 7 days): Fix the vulnerability, implement additional safeguards.
5. **Review** (within 30 days): Post-incident review, update security practices.

**FR-17.49**: The breach response plan SHALL be documented in `SECURITY.md` at the repository root.

**FR-17.50**: Breach notification SHALL include:
- What data was exposed.
- When the breach occurred and when it was detected.
- What steps are being taken.
- What players should do (change password, etc.).
- Contact information for questions.

### 11.2 Edge Cases

- **EC-17.6**: If a breach affects only system data (no player PII), a public notice is sufficient (no individual notification).
- **EC-17.7**: If the breach is via a third-party provider (LLM provider compromised), TTA SHALL inform players and link to the provider's breach notice.

### 11.3 Acceptance Criteria

- [ ] `SECURITY.md` contains a breach response plan.
- [ ] The breach plan includes timelines for each response phase.
- [ ] Notification template exists (fill-in-the-blanks, not drafted from scratch during a crisis).

---

## 12. Privacy Policy

### 12.1 Functional Requirements

**FR-17.51**: TTA SHALL have a privacy policy accessible at `/privacy` that covers:
1. What data is collected (Section 1 of this spec).
2. How data is used.
3. Who data is shared with (Section 7).
4. Player rights (Section 3).
5. Data retention (Section 4).
6. Children's privacy (Section 9).
7. NOT HIPAA statement (Section 8).
8. Contact information for privacy questions.
9. How to request data export or deletion.
10. Cookie/tracking disclosure (TTA v1 uses session cookies only, no third-party trackers).

**FR-17.52**: The privacy policy SHALL be written in plain language. No legalese. A 16-year-old should be able to understand it.

**FR-17.53**: The privacy policy SHALL include a "last updated" date. Players SHALL be notified when the policy changes.

**FR-17.54**: The privacy policy SHALL be versioned in the repository alongside the code.

### 12.2 Acceptance Criteria

- [ ] `/privacy` returns the privacy policy.
- [ ] The privacy policy covers all items listed in FR-17.51.
- [ ] The privacy policy is understandable by a non-lawyer.
- [ ] The privacy policy is version-controlled.

---

## Key Scenarios (Gherkin)

```gherkin
Scenario: Player exports all personal data
  Given a player with ID "player_42" has an active account and 3 completed sessions
  When the player requests "GET /api/player/me/data-export"
  Then an async export job is created
  And within 72 hours a download link is provided
  And the JSON export contains player profile, all session histories, and consent records

Scenario: Player requests account erasure
  Given a player with ID "player_42" has data in PostgreSQL, Neo4j, Redis, and Langfuse
  When the player requests "DELETE /api/player/me"
  Then all player data is removed from PostgreSQL
  And all player nodes and connected game state are removed from Neo4j
  And cached session data is removed from Redis
  And a Langfuse deletion request is submitted for the player's pseudonymized ID
  And the deletion is confirmed within 30 days
  And consent records are preserved in anonymized form

Scenario: Consent required before account creation
  Given a new player attempts to create an account
  When the player declines the required "Core gameplay" consent category
  Then account creation is denied
  And the system displays a clear explanation of why consent is required
  And no player data is stored

Scenario: Age restriction enforced at registration
  Given a new player is on the account creation screen
  When the player does not confirm they are 13 years of age or older
  Then account creation is denied
  And no player data is collected or stored
```

---

## Appendix A: Data Flow Diagram

```
Player Input
    │
    ▼
[TTA API] ──── Player profile ────→ [PostgreSQL]
    │                                     │
    │                                     └── Consent records
    │
    ├── Session state ────────────→ [Redis] (24h TTL)
    │
    ├── Game state/history ───────→ [Neo4j]
    │
    ├── Full prompt + response ───→ [Langfuse]
    │
    └── Player input + prompt ────→ [LLM Provider API]
                                        │
                                        └── (data processed per provider policy,
                                             NOT stored by TTA)
```

## Appendix B: GDPR Quick Reference

| Right | TTA Implementation | Endpoint |
|-------|-------------------|----------|
| Access | Full data export (JSON) | `GET /api/player/me/data-export` |
| Erasure | Delete all personal data | `DELETE /api/player/me` |
| Portability | Same as access (JSON format) | `GET /api/player/me/data-export` |
| Rectification | Update profile fields | `PATCH /api/player/me` |
| Object to processing | Withdraw optional consent | `PATCH /api/player/me/consent` |

## Appendix C: v1 vs Future Privacy Maturity

| Capability | v1 | Future |
|-----------|-----|--------|
| Data export | API endpoint, manual Langfuse pull | Fully automated, all sources |
| Data erasure | API endpoint, Langfuse manual delete | Fully automated cascade |
| Encryption at rest | Infrastructure-level | Application-level (field encryption) |
| Age verification | Self-declaration | Age verification service |
| HIPAA compliance | Explicitly not | Possible with BAAs, audit controls |
| Privacy officer | None | Designated (if commercialized) |
| Breach response | Basic plan | Incident response team, automated detection |
| Anonymization | Manual script | Automated pipeline |
