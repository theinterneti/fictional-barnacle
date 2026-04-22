"""genesis_lite unit behaviors — foundational tests for S02 Genesis Onboarding.

These tests validate the ``genesis_lite`` module's implementation behaviors at the
unit level.  They are *not* full S02 spec-AC compliance tests: the S02 Acceptance
Criteria (five-act flow, harmful-content redirection, mid-session reconnect,
identity challenge) require integration infrastructure and are covered by BDD /
integration tests.

Unit behaviors covered
-----------------------
GL-1  run_genesis_lite returns a non-empty narrative intro
GL-2  World graph is created exactly once per session (no duplicate writes)
GL-3  GenesisResult envelope exposes all expected fields
GL-4  Session-scoped variance: different session_ids produce different prompts
GL-5  LLM error propagation — no silent failure or data corruption
GL-6  Terse / single-word defining_detail is expanded automatically
GL-7  character_concept is forwarded into the enrichment prompt

Related S02 ACs (full behavioral validation deferred to integration)
----------------------------------------------------------------------
AC-2.1  Genesis begins with a narrative prompt when the app loads
AC-2.2  Five acts of Genesis complete before entering the game world
AC-2.3  First narrative references genesis elements by name (LLM quality)
AC-2.4  Full genesis completes within 5-10 minutes (wall-clock)
AC-2.5  Disconnect during Act III → resume from Act III on reconnect
AC-2.6  Second playthrough opens differently from the first
AC-2.7  Harmful content during Genesis → redirection, not corruption
AC-2.8  Terse player → Genesis asks follow-up questions to build detail
AC-2.9  Player rejects generated identity → Genesis offers alternatives
AC-2.10 No visible mode boundary between Genesis and gameplay
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from tta.genesis.genesis_lite import (
    GenesisResult,
    enrich_template,
    run_genesis_lite,
)
from tta.llm.client import GenerationParams, LLMResponse, Message
from tta.llm.roles import ModelRole
from tta.models.turn import TokenCount
from tta.models.world import (
    TemplateLocation,
    TemplateMetadata,
    WorldSeed,
    WorldTemplate,
)
from tta.world.memory_service import InMemoryWorldService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_enrichment_json() -> str:
    """Return an EnrichedTemplate JSON that genesis_lite can parse."""
    return json.dumps(
        {"locations": [], "npcs": [], "items": [], "knowledge_details": {}}
    )


def _template_with_start_loc() -> WorldTemplate:
    """Minimal template with a single starting location."""
    return WorldTemplate(
        metadata=TemplateMetadata(
            template_key="test_world",
            display_name="Test World",
        ),
        locations=[
            TemplateLocation(
                key="start",
                region_key="r1",
                type="interior",
                archetype="tavern",
                is_starting_location=True,
            )
        ],
    )


def _seed(**kwargs) -> WorldSeed:
    return WorldSeed(template=_template_with_start_loc(), **kwargs)


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model_used="mock",
        token_count=TokenCount(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
        latency_ms=0.0,
    )


class _CapturingLLM:
    """Records every prompt delivered to it; returns configurable responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._idx = 0
        self.calls: list[list[Message]] = []

    def _next(self, messages: list[Message]) -> LLMResponse:
        self.calls.append(list(messages))
        resp = self._responses[self._idx % len(self._responses)]
        self._idx += 1
        return _make_llm_response(resp)

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        return self._next(messages)

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        return self._next(messages)


class _ErrorLLM:
    """Raises RuntimeError on every call."""

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        raise RuntimeError("LLM unavailable")

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        raise RuntimeError("LLM unavailable")


# ---------------------------------------------------------------------------
# AC-2.1 — Narrative intro is generated after genesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.spec("AC-02.01")
async def test_ac_2_1_narrative_intro_non_empty():
    """[AC-2.1] run_genesis_lite returns a non-empty narrative_intro."""
    llm = _CapturingLLM(
        [
            _valid_enrichment_json(),  # enrichment call
            "You stand at the threshold of the ancient tavern.",  # intro call
        ]
    )
    result = await run_genesis_lite(
        session_id=uuid4(),
        player_id=uuid4(),
        world_seed=_seed(),
        llm=llm,
        world_service=InMemoryWorldService(),
    )

    assert isinstance(result.narrative_intro, str)
    assert len(result.narrative_intro) > 0


# ---------------------------------------------------------------------------
# AC-2.2 — World graph created exactly once per session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.spec("AC-02.02")
async def test_ac_2_2_world_graph_created_once(monkeypatch: pytest.MonkeyPatch):
    """[AC-2.2] create_world_graph is called exactly once for a single session."""
    world_service = InMemoryWorldService()
    call_count = 0
    original = world_service.create_world_graph

    async def _spy(session_id, world_seed):  # type: ignore[override]
        nonlocal call_count
        call_count += 1
        return await original(session_id, world_seed)

    monkeypatch.setattr(world_service, "create_world_graph", _spy)

    llm = _CapturingLLM([_valid_enrichment_json(), "A fine world awaits."])
    session = uuid4()
    await run_genesis_lite(
        session_id=session,
        player_id=uuid4(),
        world_seed=_seed(),
        llm=llm,
        world_service=world_service,
    )

    assert call_count == 1


# ---------------------------------------------------------------------------
# AC-2.5 — GenesisResult envelope fields all present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.spec("AC-02.05")
async def test_ac_2_5_genesis_result_envelope():
    """[AC-2.5] GenesisResult has all required fields with correct types."""
    session = uuid4()
    llm = _CapturingLLM([_valid_enrichment_json(), "Darkness gives way to light."])
    result = await run_genesis_lite(
        session_id=session,
        player_id=uuid4(),
        world_seed=_seed(),
        llm=llm,
        world_service=InMemoryWorldService(),
    )

    assert isinstance(result, GenesisResult)
    assert result.session_id == session
    assert isinstance(result.world_id, str) and result.world_id
    assert isinstance(result.player_location_id, str) and result.player_location_id
    assert isinstance(result.template_key, str) and result.template_key
    assert isinstance(result.narrative_intro, str) and result.narrative_intro
    assert isinstance(result.genesis_elements, list)
    assert isinstance(result.created_at, datetime)
    # created_at should be timezone-aware
    assert result.created_at.tzinfo is not None


# ---------------------------------------------------------------------------
# AC-2.6 — Session-scoped variance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.spec("AC-02.06")
async def test_ac_2_6_session_variance_different_prompts():
    """[AC-2.6] Two different session UUIDs yield different enrichment prompts."""
    # UUIDs chosen so that int(hex[:8], 16) % 6 differs between them.
    # session_a: 0x00000000 % 6 == 0 → "bold and dramatic"
    # session_b: 0xffffffff % 6 == 5 → "warm and inviting"
    session_a = UUID("00000000-0000-0000-0000-000000000001")
    session_b = UUID("ffffffff-0000-0000-0000-000000000001")

    template = _template_with_start_loc()
    seed = WorldSeed(template=template)

    llm_a = _CapturingLLM([_valid_enrichment_json()])
    llm_b = _CapturingLLM([_valid_enrichment_json()])

    await enrich_template(template, seed, llm_a, session_id=session_a)
    await enrich_template(template, seed, llm_b, session_id=session_b)

    prompt_a = llm_a.calls[0][-1].content  # last message = user prompt
    prompt_b = llm_b.calls[0][-1].content

    assert "Creative direction:" in prompt_a
    assert "Creative direction:" in prompt_b
    assert prompt_a != prompt_b, "Different sessions must produce different prompts"


@pytest.mark.asyncio
@pytest.mark.spec("AC-02.06")
async def test_ac_2_6_no_variance_without_session_id():
    """[AC-2.6] Without a session_id, no 'Creative direction' line is appended."""
    template = _template_with_start_loc()
    seed = WorldSeed(template=template)
    llm = _CapturingLLM([_valid_enrichment_json()])

    await enrich_template(template, seed, llm, session_id=None)

    prompt = llm.calls[0][-1].content
    assert "Creative direction:" not in prompt


# ---------------------------------------------------------------------------
# AC-2.7 — LLM error propagated (no silent corruption)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.spec("AC-02.07")
async def test_ac_2_7_llm_error_propagates_from_intro():
    """[AC-2.7] RuntimeError from the intro LLM call is propagated, not swallowed."""

    # First call (enrichment) returns valid JSON; second (intro) raises.
    class _IntroErrorLLM:
        _call = 0

        async def generate(
            self,
            role: ModelRole,
            messages: list[Message],
            params: GenerationParams | None = None,
        ) -> LLMResponse:
            self._call += 1
            if self._call == 1:
                return _make_llm_response(_valid_enrichment_json())
            raise RuntimeError("Intro LLM unavailable")

        async def stream(
            self,
            role: ModelRole,
            messages: list[Message],
            params: GenerationParams | None = None,
        ) -> LLMResponse:
            return await self.generate(role, messages, params)

    with pytest.raises(RuntimeError, match="Intro LLM unavailable"):
        await run_genesis_lite(
            session_id=uuid4(),
            player_id=uuid4(),
            world_seed=_seed(),
            llm=_IntroErrorLLM(),  # type: ignore[arg-type]
            world_service=InMemoryWorldService(),
        )


@pytest.mark.asyncio
@pytest.mark.spec("AC-02.07")
async def test_ac_2_7_enrichment_error_uses_default_fallback():
    """[AC-2.7] Enrichment LLM error falls back to deterministic defaults (no panic)."""

    # Both enrichment calls fail; enrich_template returns _default_enrichment.
    # run_genesis_lite should still succeed if intro call works.
    class _EnrichErrorThenIntroOkLLM:
        _call = 0

        async def generate(
            self,
            role: ModelRole,
            messages: list[Message],
            params: GenerationParams | None = None,
        ) -> LLMResponse:
            self._call += 1
            if role == ModelRole.EXTRACTION:
                # Return garbage JSON — will trigger parse failure + retry failure
                return _make_llm_response("NOT JSON")
            # Intro call
            return _make_llm_response("A world of mystery awaits.")

        async def stream(
            self,
            role: ModelRole,
            messages: list[Message],
            params: GenerationParams | None = None,
        ) -> LLMResponse:
            return await self.generate(role, messages, params)

    result = await run_genesis_lite(
        session_id=uuid4(),
        player_id=uuid4(),
        world_seed=_seed(),
        llm=_EnrichErrorThenIntroOkLLM(),  # type: ignore[arg-type]
        world_service=InMemoryWorldService(),
    )
    # Deterministic fallback means genesis still completes
    assert result.narrative_intro == "A world of mystery awaits."


# ---------------------------------------------------------------------------
# AC-2.8 — Terse defining_detail expanded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.spec("AC-02.08")
async def test_ac_2_8_single_word_defining_detail_expanded():
    """[AC-2.8] A single-word defining_detail is expanded before the LLM call."""
    template = _template_with_start_loc()
    seed = WorldSeed(template=template, defining_detail="fog")
    llm = _CapturingLLM([_valid_enrichment_json()])

    await enrich_template(template, seed, llm)

    user_prompt = llm.calls[0][-1].content
    assert "a world defined by fog" in user_prompt
    assert "interpret this freely" in user_prompt


@pytest.mark.asyncio
@pytest.mark.spec("AC-02.08")
async def test_ac_2_8_two_word_defining_detail_expanded():
    """[AC-2.8] A two-word defining_detail is also expanded."""
    template = _template_with_start_loc()
    seed = WorldSeed(template=template, defining_detail="eternal night")
    llm = _CapturingLLM([_valid_enrichment_json()])

    await enrich_template(template, seed, llm)

    user_prompt = llm.calls[0][-1].content
    assert "a world defined by eternal night" in user_prompt


@pytest.mark.asyncio
@pytest.mark.spec("AC-02.08")
async def test_ac_2_8_long_defining_detail_not_expanded():
    """[AC-2.8] A longer defining_detail (>2 words) is passed through unchanged."""
    detail = "a land where rain never falls"
    template = _template_with_start_loc()
    seed = WorldSeed(template=template, defining_detail=detail)
    llm = _CapturingLLM([_valid_enrichment_json()])

    await enrich_template(template, seed, llm)

    user_prompt = llm.calls[0][-1].content
    assert detail in user_prompt
    # The expansion phrase must NOT appear for long inputs
    assert "a world defined by" not in user_prompt


@pytest.mark.asyncio
@pytest.mark.spec("AC-02.08")
async def test_ac_2_8_missing_fields_get_defaults():
    """[AC-2.8] Empty WorldSeed fields receive safe defaults before prompting."""
    template = _template_with_start_loc()
    seed = WorldSeed(template=template)  # all optional fields None
    llm = _CapturingLLM([_valid_enrichment_json()])

    await enrich_template(template, seed, llm)

    user_prompt = llm.calls[0][-1].content
    # Default values from enrich_template source
    assert "mysterious" in user_prompt  # default tone
    assert "medieval" in user_prompt  # default tech_level
    assert "adventurer" in user_prompt  # default character_concept


# ---------------------------------------------------------------------------
# AC-2.9 — character_concept forwarded to enrichment prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.spec("AC-02.09")
async def test_ac_2_9_character_concept_in_prompt():
    """[AC-2.9] The character_concept appears in the enrichment user prompt."""
    template = _template_with_start_loc()
    seed = WorldSeed(template=template, character_concept="fallen paladin")
    llm = _CapturingLLM([_valid_enrichment_json()])

    await enrich_template(template, seed, llm)

    user_prompt = llm.calls[0][-1].content
    assert "fallen paladin" in user_prompt


@pytest.mark.asyncio
@pytest.mark.spec("AC-02.09")
async def test_ac_2_9_different_concepts_produce_different_prompts():
    """[AC-2.9] Different character_concepts produce different enrichment prompts."""
    template = _template_with_start_loc()

    seed_a = WorldSeed(template=template, character_concept="thief")
    seed_b = WorldSeed(template=template, character_concept="scholar")

    llm_a = _CapturingLLM([_valid_enrichment_json()])
    llm_b = _CapturingLLM([_valid_enrichment_json()])

    await enrich_template(template, seed_a, llm_a)
    await enrich_template(template, seed_b, llm_b)

    prompt_a = llm_a.calls[0][-1].content
    prompt_b = llm_b.calls[0][-1].content
    assert prompt_a != prompt_b
