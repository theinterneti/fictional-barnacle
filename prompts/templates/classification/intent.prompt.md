---
id: classification.intent
version: "2.0.0"
role: classification
description: >
  Structured JSON intent classification with entities, emotional tone,
  and summary. Designed for free-model JSON output reliability.
parameters:
  temperature: 0.1
  max_tokens: 200
required_variables: []
optional_variables: []
---
YOU MUST RESPOND WITH ONLY A VALID JSON OBJECT. No explanation, no markdown
preamble — just the JSON object on a single line or wrapped in ```json```.

Given the player's input in the user message, classify the intent into
exactly ONE of these categories: move, examine, talk, use, meta, other.

Return a JSON object with these fields:
- "intent": one of [move, examine, talk, use, meta, other]
- "confidence": float 0.0-1.0 (how certain you are)
- "entities": list of strings (items, characters, directions mentioned)
- "emotional_tone": short string (e.g. curious, urgent, playful, neutral)
- "summary": one sentence describing the player's goal

Example: {"intent":"examine","confidence":0.85,"entities":["rusty key","locked door"],"emotional_tone":"curious","summary":"Player wants to inspect items in the room"}
