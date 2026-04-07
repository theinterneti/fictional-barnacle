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
        created_at=datetime.now(UTC),
    )


# -- Enrichment --------------------------------------------------


async def enrich_template(
    template: WorldTemplate,
    world_seed: WorldSeed,
    llm: LLMClient,
) -> EnrichedTemplate:
    """Ask the LLM to generate names / descriptions.

    On parse failure the call is retried once with error
    context.  If the retry also fails, a deterministic
    default enrichment is returned.
    """
    template_json = _build_template_summary(template)
    user_prompt = ENRICHMENT_USER_PROMPT.format(
        tone=world_seed.tone or "mysterious",
        tech_level=world_seed.tech_level or "medieval",
        magic_presence=world_seed.magic_presence or "low",
        world_scale=world_seed.world_scale or "village",
        defining_detail=world_seed.defining_detail or "",
        character_concept=(world_seed.character_concept or "adventurer"),
        template_json=template_json,
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


def _build_template_summary(
    template: WorldTemplate,
) -> str:
    """Serialise template entities to compact JSON."""
    summary: dict[str, list[dict[str, str]]] = {
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
    npcs = [
        EnrichedEntity(
            key=npc.key,
            name=npc.archetype.replace("_", " ").title(),
            description=(f"A {npc.role} — the {npc.archetype}."),
            personality="reserved",
            dialogue_style="plain spoken",
        )
        for npc in template.npcs
    ]
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
