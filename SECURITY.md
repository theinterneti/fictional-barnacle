# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| main    | ✅         |

Only the latest commit on `main` receives security updates.

---

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

1. Email **security@tta-game.example** with:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact assessment
2. You will receive an acknowledgement within **48 hours**.
3. We aim to provide a fix or mitigation within **7 days** of confirmation.

If you do not receive a response within 48 hours, follow up via the same
email address.

---

## Data Breach Response Plan

*Per S17 FR-17.46–FR-17.50.*

### Detection Signals (FR-17.47)

- Unauthorized database access or unusual query patterns
- Exposed environment variables or secrets in logs / public repos
- Player reports of unauthorized account access
- Unexpected data exports or bulk queries

### Response Timeline (FR-17.48)

| Phase       | Deadline                    | Actions                                                                                         |
|-------------|-----------------------------|-------------------------------------------------------------------------------------------------|
| **Contain** | Within 1 hour of detection  | Revoke compromised credentials, rotate API keys, disable affected endpoints                     |
| **Assess**  | Within 24 hours             | Determine exposed data, number of affected players, attack vector                               |
| **Notify**  | Within 72 hours of confirm  | Inform affected players via email, post public notice, notify GDPR authority if applicable       |
| **Remediate** | Within 7 days             | Fix the vulnerability, deploy additional safeguards                                             |
| **Review**  | Within 30 days              | Post-incident review, update security practices, publish lessons learned                        |

### Breach Notification Template (FR-17.50)

When notifying affected players, include:

```
Subject: [TTA] Security Incident Notification

What happened:
  [Description of the breach]

When it happened:
  [Date/time of breach and date/time of detection]

What data was exposed:
  [List of affected data categories]

What we are doing:
  [Steps being taken to contain and remediate]

What you should do:
  [Recommended player actions — e.g., change password]

Contact:
  security@tta-game.example
```

### Edge Cases

- **System-only breach** (no player PII): a public notice is sufficient;
  individual notification is not required (EC-17.6).
- **Third-party breach** (e.g., LLM provider compromised): inform players
  and link to the provider's breach notice (EC-17.7).

---

## Security Practices

### Authentication

- Admin API uses Bearer token authentication with timing-safe comparison
  (`secrets.compare_digest`).
- Player sessions use opaque tokens stored server-side.

### Data Protection

- All database connections use TLS in production.
- PII fields are classified in the data model (S17 FR-17.5).
- Completed game sessions are automatically purged after 90 days
  (S17 FR-17.15).
- Application logs are retained for 30 days maximum.

### Infrastructure

- Security headers (CSP, HSTS, X-Content-Type-Options, X-Frame-Options,
  Referrer-Policy, Permissions-Policy) are applied to all responses.
- Rate limiting protects against brute-force and abuse (S25).
- Content moderation scans all player input (S24).

### Dependencies

- Dependencies are managed via `uv` with a locked `uv.lock` file.
- Dependabot is configured for automated security updates.
