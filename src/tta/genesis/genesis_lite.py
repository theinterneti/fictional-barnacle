"""Genesis-Lite — lightweight world bootstrap flow."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from uuid import UUID

import structlog
from pydantic import BaseModel, Field

from tta.genesis.prompts import (
    ENRICHMENT_SYSTEM_PROMPT,
    ENRICHMENT_USER_PROMPT,
    INTRO_SYSTEM_PROMPT,
    INTRO_USER_PROMPT,
)
from tta.llm.client import LLMClient, Message, MessageRole
from tta.llm.roles import ModelRole
from tta.models.world import WorldSeed, WorldTemplate
from tta.world.service import WorldService

log = structlog.get_logger(__name__)


# -- Result and enrichment models --------------------------------


class EnrichedEntity(BaseModel):
    """Enriched entity with generated name and description."""

    key: str
    name: str
    description: str
    description_visited: str | None = None
    personality: str | None = None
    dialogue_style: str | None = None
    # Wave 5 — NPC character depth (S06 FR-3)
    voice: str | None = None
    occupation: str | None = None
    goals_short: str | None = None
    backstory_summary: str | None = None


class EnrichedTemplate(BaseModel):
    """LLM-generated enrichment for a world template."""

    locations: list[EnrichedEntity] = Field(
        default_factory=list,
    )
    npcs: list[EnrichedEntity] = Field(
        default_factory=list,
    )
    items: list[EnrichedEntity] = Field(
        default_factory=list,
    )
    knowledge_details: dict[str, str] = Field(
        default_factory=dict,
    )


class GenesisResult(BaseModel):
    """Result of a genesis-lite world bootstrap."""

    session_id: UUID
    world_id: str
    player_location_id: str
    template_key: str
    narrative_intro: str
    genesis_elements: list[str] = Field(
        default_factory=list,
        description=(
            "Key world elements established during genesis — location names, "
            "NPC names, notable items. Injected into early turns for "
            "continuity (S02 AC-2.3, AC-2.10)."
        ),
    )
    created_at: datetime


# -- Public API --------------------------------------------------


async def run_genesis_lite(
    session_id: UUID,
    player_id: UUID,
    world_seed: WorldSeed,
    llm: LLMClient,
    world_service: WorldService,
) -> GenesisResult:
    """Bootstrap a new game world from a seed and template.

    Steps
    -----
    1. Enrich template entities via LLM (names / descriptions).
    2. Store enrichment in ``flavor_text`` and create the world
       graph through the world service.
    3. Resolve the starting location.
    4. Generate a narrative introduction.
    5. Return a :class:`GenesisResult`.
    """
    template = world_seed.template
    template_key = template.metadata.template_key
    log.info(
        "genesis_lite_start",
        session_id=str(session_id),
        template_key=template_key,
    )

    # 1 — enrich template entities via LLM
    enriched = await enrich_template(
        template,
        world_seed,
        llm,
        session_id=session_id,
    )

    # 2 — build enriched seed and materialise the world graph
    enriched_seed = world_seed.model_copy(
        update={"flavor_text": enriched.model_dump()},
    )
    await world_service.create_world_graph(
        session_id,
        enriched_seed,
    )

    # 3 — resolve starting location
    player_loc = await world_service.get_player_location(
        session_id,
    )
    loc_name, loc_desc = _enriched_location_info(
        enriched,
        player_loc.template_key,
        player_loc,
    )

    # 4 — generate narrative introduction
    narrative_intro = await _generate_intro(
        llm=llm,
        location_name=loc_name,
        location_description=loc_desc,
        world_seed=world_seed,
    )

    # 5 — extract genesis elements for post-genesis continuity
    elements = _extract_genesis_elements(enriched, loc_name)

    world_id = f"world_{template_key}_{session_id.hex[:8]}"
    log.info(
        "genesis_lite_complete",
        session_id=str(session_id),
        world_id=world_id,
        player_location=player_loc.id,
    )

    return GenesisResult(
        session_id=session_id,
        world_id=world_id,
        player_location_id=player_loc.id,
        template_key=template_key,
        narrative_intro=narrative_intro,
        genesis_elements=elements,
        created_at=datetime.now(UTC),
    )


# -- Enrichment --------------------------------------------------


async def enrich_template(
    template: WorldTemplate,
    world_seed: WorldSeed,
    llm: LLMClient,
    *,
    session_id: UUID | None = None,
) -> EnrichedTemplate:
    """Ask the LLM to generate names / descriptions.

    On parse failure the call is retried once with error
    context.  If the retry also fails, a deterministic
    default enrichment is returned.

    Terse or single-word seed values are expanded with safe
    defaults before prompting (S02 AC-2.8).

    A session-derived creativity seed is appended so repeat
    genesis with the same template produces varied output
    (S02 AC-2.6).
    """
    # Defensive expansion for terse inputs (AC-2.8)
    tone = world_seed.tone or "mysterious"
    tech_level = world_seed.tech_level or "medieval"
    magic_presence = world_seed.magic_presence or "low"
    world_scale = world_seed.world_scale or "village"
    defining_detail = world_seed.defining_detail or ""
    character_concept = world_seed.character_concept or "adventurer"

    # Expand single-word defining_detail into a richer description
    if defining_detail and len(defining_detail.split()) <= 2:
        defining_detail = (
            f"a world defined by {defining_detail} — "
            "interpret this freely to create a unique setting"
        )

    template_json = _build_template_summary(template)
    user_prompt = ENRICHMENT_USER_PROMPT.format(
        tone=tone,
        tech_level=tech_level,
        magic_presence=magic_presence,
        world_scale=world_scale,
        defining_detail=defining_detail,
        character_concept=character_concept,
        template_json=template_json,
    )

    # Session-scoped creativity variance (AC-2.6)
    if session_id is not None:
        _VARIANCE_ADJECTIVES = [
            "bold and dramatic",
            "subtle and atmospheric",
            "gritty and realistic",
            "whimsical and surprising",
            "dark and foreboding",
            "warm and inviting",
        ]
        idx = int(session_id.hex[:8], 16) % len(_VARIANCE_ADJECTIVES)
        user_prompt += (
            f"\n\nCreative direction: make this world feel {_VARIANCE_ADJECTIVES[idx]}."
        )
    messages = [
        Message(
            role=MessageRole.SYSTEM,
            content=ENRICHMENT_SYSTEM_PROMPT,
        ),
        Message(
            role=MessageRole.USER,
            content=user_prompt,
        ),
    ]

    # --- first attempt ---
    response = await llm.generate(
        ModelRole.EXTRACTION,
        messages,
    )
    first_error_msg: str | None = None
    try:
        return _parse_enrichment(response.content)
    except Exception as first_err:  # noqa: BLE001
        first_error_msg = str(first_err)
        log.warning(
            "enrichment_parse_failed",
            error=first_error_msg,
            attempt=1,
        )

    # --- retry with error context ---
    retry_messages = [
        *messages,
        Message(
            role=MessageRole.ASSISTANT,
            content=response.content,
        ),
        Message(
            role=MessageRole.USER,
            content=(
                "That response could not be parsed: "
                f"{first_error_msg}. "
                "Respond with valid JSON only."
            ),
        ),
    ]
    response = await llm.generate(
        ModelRole.EXTRACTION,
        retry_messages,
    )
    try:
        return _parse_enrichment(response.content)
    except Exception as second_err:  # noqa: BLE001
        log.warning(
            "enrichment_fallback",
            error=str(second_err),
            attempt=2,
        )
        return _default_enrichment(template)


# -- Private helpers ---------------------------------------------


def _extract_genesis_elements(
    enriched: EnrichedTemplate,
    loc_name: str,
) -> list[str]:
    """Extract key world elements established during genesis (S02 AC-2.3).

    Returns a compact list of names/facts the narrative can reference
    in early post-genesis turns for continuity.
    """
    elements: list[str] = []
    elements.append(f"Starting location: {loc_name}")
    for npc in enriched.npcs:
        label = npc.name
        if npc.occupation:
            label += f" ({npc.occupation})"
        elements.append(f"NPC: {label}")
    for item in enriched.items:
        elements.append(f"Notable object: {item.name}")
    for loc in enriched.locations:
        if loc.name != loc_name:
            elements.append(f"Nearby area: {loc.name}")
    return elements


def _build_template_summary(
    template: WorldTemplate,
) -> str:
    """Serialise template entities to compact JSON."""
    summary: dict[str, list[dict[str, object]]] = {
        "locations": [
            {
                "key": loc.key,
                "archetype": loc.archetype,
                "type": loc.type,
            }
            for loc in template.locations
        ],
        "npcs": [
            {
                "key": npc.key,
                "archetype": npc.archetype,
                "role": npc.role,
                **({"tier": npc.tier} if npc.tier else {}),
                **({"traits": npc.traits} if npc.traits else {}),
                **({"goals_hint": npc.goals_hint} if npc.goals_hint else {}),
                **(
                    {"backstory_hint": npc.backstory_hint} if npc.backstory_hint else {}
                ),
            }
            for npc in template.npcs
        ],
        "items": [
            {
                "key": item.key,
                "archetype": item.archetype,
                "type": item.type,
            }
            for item in template.items
        ],
        "knowledge": [
            {
                "npc_key": k.npc_key,
                "about_key": k.about_key,
                "type": k.knowledge_type,
            }
            for k in template.knowledge
        ],
    }
    return json.dumps(summary, indent=2)


def _parse_enrichment(raw: str) -> EnrichedTemplate:
    """Parse LLM output as EnrichedTemplate JSON."""
    text = raw.strip()
    # Strip markdown code fences if present.
    fence = re.search(
        r"```(?:json)?\s*\n(.*?)\n```",
        text,
        re.DOTALL,
    )
    if fence:
        text = fence.group(1)
    return EnrichedTemplate.model_validate_json(text)


def _default_enrichment(
    template: WorldTemplate,
) -> EnrichedTemplate:
    """Deterministic fallback using template archetypes."""
    locations = [
        EnrichedEntity(
            key=loc.key,
            name=loc.archetype.replace("_", " ").title(),
            description=f"A {loc.archetype} area.",
        )
        for loc in template.locations
    ]
    npcs = []
    for npc in template.npcs:
        tier = npc.tier or "background"
        if tier == "key":
            personality = "complex and driven"
            dialogue_style = "distinctive and memorable"
            voice = "authoritative with personal warmth"
            occupation = npc.role or "leader"
            goals_short = npc.goals_hint or "pursuing a personal quest"
            backstory_summary = (
                npc.backstory_hint or f"A {npc.archetype} with a storied past."
            )
        elif tier == "supporting":
            personality = "helpful and grounded"
            dialogue_style = "conversational"
            voice = "friendly and practical"
            occupation = npc.role or "artisan"
            goals_short = npc.goals_hint or "supporting the community"
            backstory_summary = None
        else:
            personality = "reserved"
            dialogue_style = "plain spoken"
            voice = None
            occupation = None
            goals_short = None
            backstory_summary = None
        npcs.append(
            EnrichedEntity(
                key=npc.key,
                name=npc.archetype.replace("_", " ").title(),
                description=(f"A {npc.role} — the {npc.archetype}."),
                personality=personality,
                dialogue_style=dialogue_style,
                voice=voice,
                occupation=occupation,
                goals_short=goals_short,
                backstory_summary=backstory_summary,
            )
        )
    items = [
        EnrichedEntity(
            key=item.key,
            name=item.archetype.replace("_", " ").title(),
            description=(f"A {item.type} — {item.archetype}."),
        )
        for item in template.items
    ]
    return EnrichedTemplate(
        locations=locations,
        npcs=npcs,
        items=items,
    )


def _enriched_location_info(
    enriched: EnrichedTemplate,
    template_key: str | None,
    fallback_loc: object,
) -> tuple[str, str]:
    """Look up enriched name/desc for a location."""
    for eloc in enriched.locations:
        if eloc.key == template_key:
            return eloc.name, eloc.description
    name = getattr(fallback_loc, "name", "Unknown")
    desc = getattr(fallback_loc, "description", "")
    return name, desc


async def _generate_intro(
    *,
    llm: LLMClient,
    location_name: str,
    location_description: str,
    world_seed: WorldSeed,
) -> str:
    """Generate a narrative intro paragraph via LLM."""
    user_prompt = INTRO_USER_PROMPT.format(
        location_name=location_name,
        location_description=location_description,
        character_name=(world_seed.character_name or "the traveler"),
        world_tone=world_seed.tone or "mysterious",
    )
    messages = [
        Message(
            role=MessageRole.SYSTEM,
            content=INTRO_SYSTEM_PROMPT,
        ),
        Message(
            role=MessageRole.USER,
            content=user_prompt,
        ),
    ]
    response = await llm.generate(
        ModelRole.GENERATION,
        messages,
    )
    return response.content
