"""Tests for S06 Character System wave-26 enhancements.

Covers:
  - Item 1: /character display with all WorldSeed fields (AC-6.1)
  - Item 2: NPC dialogue prompt salience (AC-6.5)
  - Item 3: Companion presence in generation (AC-6.7)
  - Item 4: Revealed goal influence in dialogue (AC-6.6)
  - Item 5: Runtime /relationships with dimensions (AC-6.3)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tta.pipeline.stages.context import _identify_companions
from tta.pipeline.stages.generate import (
    _CONTEXT_META_KEYS,
    _build_generation_prompt,
    _build_npc_section,
)

# ── helpers ──────────────────────────────────────────────────────────


@dataclass
class _FakeRow:
    world_seed: dict | None = None


@dataclass
class _FakeDimensions:
    trust: int = 0
    affinity: int = 0
    respect: int = 0
    fear: int = 0
    familiarity: int = 0


@dataclass
class _FakeRelationship:
    target_id: str = "old_sage"
    dimensions: _FakeDimensions = field(default_factory=_FakeDimensions)


def _make_turn_state(**overrides):
    """Minimal TurnState-like object for prompt building."""
    from tta.pipeline.types import TurnState

    defaults = {
        "session_id": uuid4(),
        "game_id": uuid4(),
        "player_input": "look around",
        "turn_number": 1,
        "game_state": {"status": "PLAYING"},
        "world_context": {},
    }
    defaults.update(overrides)
    return TurnState(**defaults)


# ── Item 1: /character display ───────────────────────────────────────


class TestCharacterDisplay:
    """Item 1: _build_character_response shows all available fields."""

    def test_all_fields_shown(self):
        from tta.api.routes.games import _build_character_response

        row = _FakeRow(
            world_seed={
                "preferences": {
                    "character_name": "Kael",
                    "character_concept": "A fallen paladin",
                    "tone": "dark",
                    "tech_level": "medieval",
                    "magic_presence": "rare",
                    "world_scale": "kingdom",
                    "defining_detail": "A scar across left eye",
                }
            }
        )
        resp = _build_character_response(row)
        msg = resp["message"]
        assert "Kael" in msg
        assert "fallen paladin" in msg
        assert "dark" in msg
        assert "medieval" in msg
        assert "rare" in msg
        assert "kingdom" in msg
        assert "scar" in msg

    def test_missing_fields_graceful(self):
        from tta.api.routes.games import _build_character_response

        row = _FakeRow(world_seed={"preferences": {"character_name": "Ada"}})
        resp = _build_character_response(row)
        msg = resp["message"]
        assert "Ada" in msg
        assert resp["command"] == "character"

    def test_no_world_seed(self):
        from tta.api.routes.games import _build_character_response

        row = _FakeRow(world_seed=None)
        resp = _build_character_response(row)
        assert "hasn't been created" in resp["message"]


# ── Item 2: NPC dialogue prompt salience ─────────────────────────────


class TestNPCDialogueSalience:
    """Item 2: NPC section rendered in generation prompt."""

    def test_npc_section_rendered(self):
        npc = {
            "npc_name": "Elder Mirren",
            "personality": "wise and patient",
            "voice": "soft, measured cadence",
            "mannerisms": "strokes beard while thinking",
        }
        section = _build_npc_section([npc])
        assert "Elder Mirren" in section
        assert "wise and patient" in section
        assert "soft, measured cadence" in section
        assert "strokes beard" in section

    def test_npc_section_omitted_when_empty(self):
        state = _make_turn_state(world_context={})
        prompt = _build_generation_prompt(state)
        assert "NPCs in this scene" not in prompt

    def test_multiple_npcs(self):
        npcs = [
            {"npc_name": "Guard", "personality": "stern"},
            {"npc_name": "Merchant", "voice": "booming"},
        ]
        section = _build_npc_section(npcs)
        assert "Guard" in section
        assert "Merchant" in section

    def test_npc_contexts_not_in_json_dump(self):
        """npc_dialogue_contexts should be excluded from generic JSON dump."""
        assert "npc_dialogue_contexts" in _CONTEXT_META_KEYS
        state = _make_turn_state(
            world_context={
                "npc_dialogue_contexts": [{"npc_name": "Test"}],
                "custom_key": "value",
            }
        )
        prompt = _build_generation_prompt(state)
        assert "custom_key" in prompt
        assert '"npc_dialogue_contexts"' not in prompt


# ── Item 3: Companion presence ───────────────────────────────────────


class TestCompanionPresence:
    """Item 3: Companion identification and generation injection."""

    def test_companion_injected_when_eligible(self):
        wc = {
            "npc_dialogue_contexts": [
                {
                    "npc_name": "Lyra",
                    "relationship_trust": 50,
                    "relationship_affinity": 40,
                }
            ]
        }
        result = _identify_companions(wc)
        assert result["active_companions"] == ["Lyra"]

    def test_companion_omitted_when_none_eligible(self):
        wc = {
            "npc_dialogue_contexts": [
                {
                    "npc_name": "Stranger",
                    "relationship_trust": 10,
                    "relationship_affinity": 5,
                }
            ]
        }
        result = _identify_companions(wc)
        assert "active_companions" not in result

    def test_companion_in_generation_prompt(self):
        state = _make_turn_state(world_context={"active_companions": ["Lyra"]})
        prompt = _build_generation_prompt(state)
        assert "Companion(s) present: Lyra" in prompt

    def test_no_companions_no_prompt_section(self):
        state = _make_turn_state(world_context={})
        prompt = _build_generation_prompt(state)
        assert "Companion(s) present" not in prompt


# ── Item 4: Revealed goal influence ──────────────────────────────────


class TestRevealedGoalInfluence:
    """Item 4: Goals injected in NPC section when present."""

    def test_goals_injected_when_present(self):
        npc = {
            "npc_name": "Sage",
            "goals_short": "recruit the player for the rebellion",
        }
        section = _build_npc_section([npc])
        assert "recruit the player" in section
        assert "subtly steers" in section

    def test_goals_absent_when_not_provided(self):
        npc = {"npc_name": "Merchant"}
        section = _build_npc_section([npc])
        assert "subtly steers" not in section

    def test_goals_absent_when_none(self):
        npc = {"npc_name": "Guard", "goals_short": None}
        section = _build_npc_section([npc])
        assert "subtly steers" not in section


# ── Item 5: Runtime /relationships ───────────────────────────────────


class TestRuntimeRelationships:
    """Item 5: /relationships with runtime dimensions."""

    @pytest.mark.anyio
    async def test_runtime_dimensions_shown(self):
        from tta.api.routes.games import _build_relationships_response

        dims = _FakeDimensions(trust=50, affinity=40, respect=35, fear=0)
        rels = [_FakeRelationship(target_id="old_sage", dimensions=dims)]
        svc = AsyncMock()
        svc.get_relationships_for = AsyncMock(return_value=rels)

        row = _FakeRow(world_seed={"preferences": {}})
        resp = await _build_relationships_response(
            row,
            game_id=uuid4(),
            relationship_service=svc,
        )
        msg = resp["message"]
        assert "Old Sage" in msg
        assert "trusting" in msg
        assert "warm" in msg

    @pytest.mark.anyio
    async def test_dimension_labels(self):
        from tta.api.routes.games import _dimension_label

        assert _dimension_label(70, "trusting", "wary") == "very trusting"
        assert _dimension_label(35, "trusting", "wary") == "trusting"
        assert _dimension_label(0, "trusting", "wary") == "neutral"
        assert _dimension_label(-20, "trusting", "wary") == "wary"
        assert _dimension_label(-50, "trusting", "wary") == "very wary"

    @pytest.mark.anyio
    async def test_fallback_to_template(self):
        from tta.api.routes.games import _build_relationships_response

        svc = AsyncMock()
        svc.get_relationships_for = AsyncMock(return_value=[])

        row = _FakeRow(
            world_seed={
                "preferences": {},
                "genesis": {"template_key": "test_tmpl"},
            }
        )
        resp = await _build_relationships_response(
            row,
            game_id=uuid4(),
            relationship_service=svc,
            template_registry=None,
        )
        assert resp["command"] == "relationships"
