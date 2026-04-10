# TTA Privacy Policy

**Last Updated**: 2026-07-14
**Version**: 1.0

---

## What This Policy Covers

This privacy policy explains what data the Therapeutic Text Adventure (TTA)
collects, how it is used, and what rights you have. We wrote this in plain
language so anyone can understand it.

TTA is an open-source, self-hosted game. The operator who runs your instance
controls where your data lives. This policy describes the default behavior of
the software.

---

## 1. What Data We Collect

### Player Profile

- **Player ID** — a random identifier, not your real name.
- **Display name** — optional, whatever you choose.
- **Email address** — only if used for login.
- **Password** — stored as a one-way hash (bcrypt). We never see your actual
  password.
- **Account dates** — when you signed up and last logged in.
- **Consent records** — proof that you agreed to this policy.

### Game Data

- **World state** — the game world you are playing in (stored in Neo4j).
- **Narrative history** — the story so far, including your choices.
- **Session metadata** — which game session is active, timestamps.
- **Game progress** — your achievements and save states.

### LLM Interaction Data

When you type something in the game, your input is sent to a large language
model (LLM) provider to generate the story response. This means:

- **Your input text** is sent to the LLM provider's API.
- **System prompts** (instructions that shape the story) are also sent.
- **The LLM's response** is stored so the game can show you the story.
- **Token counts and model info** are logged for monitoring.

### System Data

- **Application logs** — error messages and performance data. These do not
  contain your personal information.
- **Metrics** — numbers like "how many requests per second" (no personal data).
- **Traces** — request timing data for debugging (no personal data).

---

## 2. How Your Data Is Used

Your data is used for:

- **Running the game** — generating narrative responses, tracking your progress,
  saving your game state.
- **Monitoring** — making sure the service is working correctly.
- **Improving the service** — aggregated, anonymized statistics may be used to
  improve the game.

Your data is **never** used for:

- Advertising or marketing.
- Selling to third parties.
- Training AI models (we use API endpoints that opt out of training).

---

## 3. Who Your Data Is Shared With

| Service | What Is Shared | Why |
|---------|---------------|-----|
| **LLM Provider** (e.g., OpenAI, Anthropic) | Your input text and system prompts | To generate story responses |
| **Langfuse** (if enabled) | Full prompts, responses, and a pseudonymized player ID | LLM observability and debugging |

- We use LLM API configurations that **do not** allow the provider to train on
  your data.
- Self-hosted Langfuse is recommended so your data stays on your server.
- Each provider's own privacy policy also applies. Check their websites for
  details.

If the LLM provider changes, this policy will be updated and players will be
notified.

---

## 4. Your Rights

You have the right to:

- **See your data** — Request a copy of everything TTA has about you via the
  data export API.
- **Delete your data** — Request that all your data be erased from all storage
  systems.
- **Export your data** — Get your data in a standard JSON format that you can
  take elsewhere.
- **Withdraw consent** — Stop using TTA at any time. Your data will be retained
  per the schedule below unless you request deletion.

### How to Exercise Your Rights

- **Data export**: `GET /api/player/me/data-export` (when implemented)
- **Account deletion**: `DELETE /api/player/me` (when implemented)
- **Questions**: Contact the instance operator (see Section 8 below)

---

## 5. Data Retention

Your data is kept for specific periods, then automatically deleted:

| Data | How Long | Why |
|------|----------|-----|
| Player profile | As long as your account exists | Needed for login |
| Game sessions | Session lifetime + 30 days | So you can resume |
| Session metadata | Redis: 24 hours; PostgreSQL: 90 days | Active play, then archival |
| LLM interaction logs | 90 days (in Langfuse) | Debugging and quality |
| Application logs | 30 days | Operational monitoring |
| Metrics | 30 days | Performance monitoring |
| Traces | 7 days | Request debugging |
| Consent records | Permanent | Legal requirement |

After these periods, data is automatically purged.

---

## 6. Children's Privacy

**TTA requires players to be 13 years of age or older.** This is a
[COPPA](https://www.ftc.gov/legal-library/browse/rules/childrens-online-privacy-protection-rule-coppa)
boundary — supporting younger players would require verifiable parental consent,
which TTA does not currently implement.

- Account creation requires confirming you are 13 or older.
- TTA does not knowingly collect data from children under 13.
- If we discover that data belongs to a child under 13, it will be deleted
  immediately.

---

## 7. TTA Is Not a Medical Service

**TTA is NOT HIPAA-compliant.** It is a narrative game, not a healthcare service.

Specifically:

- No Business Associate Agreements (BAAs) are in place with LLM providers.
- Audit controls do not meet HIPAA standards.
- There is no designated privacy officer.
- Encryption at rest depends on the operator's infrastructure.

**TTA is a narrative game for self-reflection. It is not a substitute for
professional mental health care.** If you are in crisis, please contact a crisis
helpline in your country (e.g., 988 Suicide & Crisis Lifeline in the US).

---

## 8. Contact

For privacy questions about a specific TTA instance, contact the operator who
runs it. For questions about the TTA software itself:

- Open an issue on the [GitHub repository](https://github.com/theinterneti/fictional-barnacle)
- Email: See the repository's SECURITY.md for security-specific contacts

---

## 9. How to Request Data Export or Deletion

1. **Log in** to your TTA account.
2. **Export**: Send a `GET` request to `/api/player/me/data-export`. You will
   receive a download link within 72 hours containing all your data in JSON
   format.
3. **Delete**: Send a `DELETE` request to `/api/player/me`. Your data will be
   removed from all TTA-controlled storage within 72 hours. Third-party data
   (Langfuse) will be removed within 30 days.
4. You will receive confirmation when deletion is complete.

---

## 10. Cookies and Tracking

TTA v1 uses **session cookies only** — a small piece of data that keeps you
logged in during your play session. We do not use:

- Third-party tracking cookies
- Analytics cookies
- Advertising cookies
- Browser fingerprinting
- Any other tracking technology

---

## Changes to This Policy

When this policy changes:

- The "Last Updated" date at the top will be updated.
- Players will be notified of material changes.
- Previous versions are available in the repository's Git history.

This policy is version-controlled alongside the TTA source code.
