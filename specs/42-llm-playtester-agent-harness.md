# S42 — LLM Playtester Agent Harness

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.1
> **Implementation Fit**: ❌ Not Started
> **Level**: 4 — Operations
> **Dependencies**: S41 (Scenario Seed Library), v1 S07 (LLM Integration), v1 S16 (Testing Strategy)
> **Related**: S43 (Human Playtester Program), S44 (Narrative Quality Evaluation), S45 (Evaluation Pipeline)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

Manual testing of a text adventure at scale is not practical. S42 defines an
automated playtesting harness that uses LLM agents with semi-randomized
taste profiles to play sessions end-to-end, producing transcripts and
agent-side commentary that feed the evaluation pipeline (S44, S45).

An **LLM Playtester** is a software agent that:
1. Selects a scenario seed (S41) or receives one from S45
2. Creates a new game session via the TTA API
3. Plays through Genesis (S40) and at least 5 gameplay turns
4. Records the full conversation transcript
5. Appends agent-side commentary: what it intended, what surprised it,
   whether it felt the narrative was coherent

The S42 harness satisfies the *necessary* half of v2.1 validation: it is
automated, scalable, and cheap to run. It does NOT replace human playtesters
(S43), which catch emotional resonance and pacing gaps that LLM agents miss.

---

## 2. Design Philosophy

### 2.1 Taste Profiles, Not Scripted Responses

LLM playtesters do not follow a script. They have a **taste profile** that
biases their responses: an impulsive player chooses boldly; a cautious player
hesitates; a verbose player writes paragraphs; a terse player writes one word.
The semi-randomized profiles ensure diverse test coverage without scripted paths.

### 2.2 Agent Commentary is a First-Class Output

A transcript alone does not tell the evaluator whether the session was good.
Each agent turn appends a brief internal commentary: "I expected to be stopped
here. The narrative let me through without acknowledging my earlier choice."
This commentary is the input to narrative coherence evaluation (S44).

### 2.3 Reproducibility via Seed

Every playtester run is associated with a `run_seed` (random integer). Given
the same `run_seed`, `scenario_seed_id`, and model, the run is reproducible.
This supports regression detection in S45.

---

## 3. User Stories

> **US-42.1** — **As a** CI engineer, I can run `make playtest` and get a
> transcript + evaluation score for a full Genesis-through-gameplay session.

> **US-42.2** — **As a** narrative designer, I can run 10 playtester personas
> against the same seed and compare transcripts to see how the narrative
> adapts to different play styles.

> **US-42.3** — **As a** quality engineer, I can replay a specific failing run
> by supplying the same `run_seed` and model to reproduce the exact interaction.

---

## 4. Persona & Taste Profile

### 4.1 TasteProfile Fields

```python
@dataclass
class TasteProfile:
    # Response style
    verbosity: float        # 0.0 (terse) – 1.0 (verbose). Default: random in [0.1, 0.9]
    boldness: float         # 0.0 (cautious) – 1.0 (impulsive). Affects choice direction.
    curiosity: float        # 0.0 (passive) – 1.0 (probing). Affects follow-up questions.

    # Narrative preferences
    genre_affinity: str     # Primary genre preference (uses S39 vocabulary). E.g. 'horror', 'comedy'.
    tone_affinity: str      # Preferred narrative tone. E.g. 'dark', 'hopeful'.
    trope_affinity: list[str]  # 0-3 tropes the agent gravitates toward.

    # Engagement model
    attention_span: float   # 0.0 (disengages fast) – 1.0 (plays full session).
    meta_awareness: float   # 0.0 (fully in-world) – 1.0 (notes game mechanics).
```

### 4.2 Built-in Persona Templates

Five named personas ship with S42. The S45 pipeline selects from these;
each run uses a persona template with minor jitter applied to all float fields
(±0.15, clamped to [0.0, 1.0]).

| Persona ID | Name | Profile Summary |
|------------|------|-----------------|
| `curious-explorer` | The Curious Explorer | High curiosity (0.9), moderate verbosity (0.6), low boldness (0.3). Asks follow-up questions. Stays in-world. |
| `impulsive-actor` | The Impulsive Actor | High boldness (0.9), low verbosity (0.2), low curiosity (0.2). Picks fast, moves on. |
| `terse-minimalist` | The Terse Minimalist | Very low verbosity (0.1), moderate boldness (0.5). Single-word or one-line responses. Tests terse-player handling (v1 AC-2.8). |
| `verbose-narrator` | The Verbose Narrator | Very high verbosity (0.9), high curiosity (0.8). Writes paragraphs. Tests long-input handling. |
| `disengaged-skeptic` | The Disengaged Skeptic | Low attention span (0.3), high meta-awareness (0.9). Likely to abandon mid-session. Tests reconnect and timeout behaviors. |

### 4.3 Persona Selection

When the S45 pipeline does not specify a persona, the harness selects one
randomly. Each run records the persona ID and jitter seed so the run is
reproducible.

---

## 5. Functional Requirements

### FR-42.01 — Session Lifecycle

A playtester run follows this sequence:

1. `PlaytesterAgent.setup(scenario_seed_id, persona_id, run_seed)` — initialise
   the random state, load the scenario seed (S41), resolve the TasteProfile.
2. `PlaytesterAgent.run()` — open a session via `POST /api/v1/games`, play
   through all 7 Genesis phases (S40), then play `min_turns` gameplay turns
   (default: 5; configurable via `PLAYTEST_MIN_TURNS` env var).
3. `PlaytesterAgent.finish()` — close the session, emit `PlaytestReport`.

### FR-42.02 — Turn Generation

For each agent turn, the agent MUST:
1. Read the most recent narrative fragment from the API response.
2. Construct an agent prompt combining the narrative + TasteProfile instructions.
3. Call the LLM (via LiteLLM, S07) to generate the player response.
4. Append commentary: 1-3 sentences on what the agent intended and what it noticed.
5. Submit the response to `POST /api/v1/games/{id}/turns`.

### FR-42.03 — Commentary Content

Agent commentary MUST be structured as a JSON object alongside each turn:

```json
{
  "turn_index": 3,
  "agent_intent": "I wanted to ask about the figure at the window.",
  "surprise_level": 0.6,
  "surprise_note": "The narrator ignored my question about the window.",
  "coherence_rating": 0.7,
  "coherence_note": "Response was vivid but did not acknowledge my earlier choice."
}
```

### FR-42.04 — Timeout and Abandon

If the API returns no response within `PLAYTEST_TURN_TIMEOUT` seconds
(default: 60), the agent logs a timeout and skips the turn. After 3
consecutive timeouts, the agent marks the run as `abandoned` and stops.

### FR-42.05 — PlaytestReport Output

Every run produces a `PlaytestReport` as a JSON file:

```json
{
  "run_id": "uuid",
  "run_seed": 42,
  "scenario_seed_id": "bus-stop-shimmer",
  "persona_id": "curious-explorer",
  "persona_jitter_seed": 17,
  "model": "gpt-4o-mini",
  "status": "complete",
  "genesis_phases_completed": 7,
  "gameplay_turns_completed": 5,
  "turns": [
    {"turn_index": 0, "phase": "void", "player_input": "...",
     "narrative": "...", "commentary": { ... }}
  ],
  "overall_agent_rating": 0.75,
  "overall_agent_notes": "Narrative was coherent. Slip event was effective."
}
```

### FR-42.06 — Reproducibility

Given the same `run_seed`, `scenario_seed_id`, `persona_id`, `persona_jitter_seed`,
and `model`, a playtester run MUST produce the same player responses.
Reproducibility applies to the *agent's responses only* — the TTA narrative
varies based on the universe seed (S39), which is separate.

### FR-42.07 — Parallel Execution

Multiple playtester agents MAY run in parallel. Each agent has its own API
session; no shared state between agents. The S45 pipeline controls concurrency.

---

## 6. PlaytesterAgent Contract

```python
class PlaytesterAgent:
    def __init__(
        self,
        api_base_url: str,
        llm_model: str = "gpt-4o-mini",
    ) -> None: ...

    def setup(
        self,
        scenario_seed_id: str,
        persona_id: str,
        run_seed: int,
    ) -> None: ...

    async def run(self) -> PlaytestReport: ...
    async def finish(self) -> PlaytestReport: ...
```

---

## 7. Acceptance Criteria (Gherkin)

```gherkin
Feature: LLM Playtester Agent Harness

  Scenario: AC-42.01 — Agent completes a full session
    Given a PlaytesterAgent with scenario_seed_id = "bus-stop-shimmer"
    And persona_id = "curious-explorer"
    And the TTA API is running
    When agent.run() completes
    Then PlaytestReport.status = "complete"
    And PlaytestReport.genesis_phases_completed = 7
    And PlaytestReport.gameplay_turns_completed >= 5

  Scenario: AC-42.02 — Every turn has commentary
    Given a completed PlaytestReport
    Then every turn in report.turns has a non-null commentary field
    And every commentary has agent_intent, surprise_level, coherence_rating

  Scenario: AC-42.03 — Run is reproducible given same seeds
    Given two runs with identical run_seed, persona_id, persona_jitter_seed, model
    Then the player_input field of each turn is identical across both runs

  Scenario: AC-42.04 — Terse persona exercises AC-2.8 path
    Given persona_id = "terse-minimalist"
    When the agent runs through Phase 4
    Then at least one turn has player_input length < 20 characters
    And the PlaytestReport is still status = "complete"

  Scenario: AC-42.05 — API timeout leads to abandoned status after 3 consecutive
    Given the TTA API times out on every turn
    When the agent has recorded 3 consecutive timeouts
    Then PlaytestReport.status = "abandoned"
    And no further turns are attempted
```

---

## 8. Out of Scope

- Human playtest sessions — S43.
- Narrative quality scoring — S44.
- Pipeline orchestration — S45.
- Browser/UI automation — LLM playtesters use the API directly.

---

## 9. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-42.01 | LLM persona count and taste-profile dimensions | ✅ Resolved | **5 built-in personas**, 8-field TasteProfile. Persona count is sufficient for v2.1; S45 selects from them. Additional personas can be added by dropping new persona YAML into `data/personas/`. |
| OQ-42.02 | Which LLM model should the playtester use? | ✅ Resolved | **`gpt-4o-mini` by default** (fast, cheap, sufficient for behavioral variety). Configurable via `PLAYTEST_LLM_MODEL` env var. Same LiteLLM client as TTA (S07). |
| OQ-42.03 | Should commentary be LLM-generated or rule-based? | ✅ Resolved | **LLM-generated** (same model as the agent's turn response, via a second call). This adds cost but produces richer evaluation input. Rule-based commentary (e.g., just turn length) is insufficient for S44. |
