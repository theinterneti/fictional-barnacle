# S18 — Therapeutic Framework

> **Status**: 📝 Stub (Future)
> **Level**: 5 — Future Vision
> **Dependencies**: S03, S08, S12
> **Last Updated**: 2025-07-24

## 1. Vision

TTA's long-term vision includes weaving evidence-based therapeutic approaches — CBT,
ACT, exposure therapy, mindfulness, motivational interviewing — into the narrative
gameplay itself. The therapy IS the game mechanic: a player facing a fear in-game is
practicing exposure therapy; a character reframing a setback is practicing CBT.

This is not a "therapy mode" bolted onto a game. It's a design philosophy where
therapeutic value emerges naturally from well-crafted narrative experiences. Players
may not even realize they're engaging with therapeutic techniques — they're just
playing a compelling game that happens to build genuine coping skills.

## 2. v1 Constraints

These architectural decisions in v1 **must** accommodate future therapeutic integration:

- **Narrative engine extensibility**: The narrative engine (S03) must support pluggable
  content strategies — a future therapeutic layer should be able to influence narrative
  generation without rewriting the engine.
- **Structured turn metadata**: Each turn's pipeline output (S08) must include structured
  metadata (intent, emotional tone, themes) — not just raw prose. Therapeutic analysis
  needs this data.
- **Session history queryability**: Session data (S12) must store conversation history
  in a structured, queryable format — not just a flat log. Therapeutic tracking needs
  to query patterns across sessions.
- **Character state extensibility**: The character system (S06) must support arbitrary
  state attributes — therapeutic frameworks will add emotional state, coping skill
  levels, and therapeutic progress markers.
- **Prompt composability**: The prompt system (S09) must support layered composition —
  therapeutic prompts will wrap or augment base narrative prompts.

## 3. Not in v1

- No therapeutic outcome tracking
- No clinical terminology in the UI
- No therapist dashboard or professional tools
- No therapeutic efficacy measurement
- No HIPAA compliance (see S17 — be honest about this)
- No clinical validation or IRB approval processes

## 4. Open Questions

1. Should therapeutic value be opt-in (player chooses "therapeutic mode") or invisible
   (always present but never labeled)?
2. What level of clinical oversight is needed before claiming therapeutic benefit?
3. How do we measure therapeutic efficacy without making the game feel clinical?
4. Should we partner with mental health professionals during the spec phase?

## 5. Related Specs

| Spec | Relationship |
|------|-------------|
| S03 (Narrative Engine) | Must support pluggable content strategies |
| S06 (Character System) | Must support extensible character state |
| S08 (Turn Pipeline) | Must emit structured metadata per turn |
| S09 (Prompt Management) | Must support layered prompt composition |
| S12 (Persistence) | Must store queryable session history |
| S19 (Crisis Safety) | Complementary — safety enables therapy |
