"""Genesis prompt templates for world enrichment and narrative intro."""

from __future__ import annotations

ENRICHMENT_SYSTEM_PROMPT = """\
You are a world-building assistant for a text adventure game.
Given a world template with archetypes, generate rich names and
descriptions for every entity.  Return ONLY valid JSON matching
the schema below — no markdown fences, no commentary.

Schema:
{
  "locations": [
    {
      "key": "<template_key>",
      "name": "<evocative name>",
      "description": "<vivid first-visit description>",
      "description_visited": "<shorter revisit description>"
    }
  ],
  "npcs": [
    {
      "key": "<template_key>",
      "name": "<character name>",
      "description": "<appearance and demeanour>",
      "personality": "<personality traits>",
      "dialogue_style": "<how they speak>"
    }
  ],
  "items": [
    {
      "key": "<template_key>",
      "name": "<item name>",
      "description": "<sensory description>"
    }
  ],
  "knowledge_details": {
    "<npc_key>:<about_key>": "<what the NPC knows>"
  }
}"""

ENRICHMENT_USER_PROMPT = """\
World parameters:
- Tone: {tone}
- Tech level: {tech_level}
- Magic presence: {magic_presence}
- World scale: {world_scale}
- Defining detail: {defining_detail}
- Character concept: {character_concept}

Template entities to enrich:
{template_json}

Generate names and descriptions for every entity above.
Match the tone and setting.  Return ONLY valid JSON."""

INTRO_SYSTEM_PROMPT = """\
You are a narrative writer for a therapeutic text adventure game.
Write an immersive but concise introductory paragraph (3-5 sentences)
that sets the scene for the player arriving at their starting
location.  Use second person ("you").  Be vivid but brief."""

INTRO_USER_PROMPT = """\
Location: {location_name}
Description: {location_description}
Character: {character_name}
World tone: {world_tone}

Write the opening narrative for this character arriving \
at this location."""
