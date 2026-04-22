"""S06 Character System — Acceptance Criteria compliance tests.

Covers AC-6.4, AC-6.8, AC-6.9.
Deferred (documented rationale only): AC-6.2, AC-6.10.

Already covered by existing tests (DO NOT duplicate):
  AC-6.1 — /character display with WorldSeed fields:
      test_s06_character_system.py
  AC-6.3 — /relationships with relationship dimensions:
      test_s06_character_system.py
  AC-6.5 — Distinct NPC vocabulary/personality markers (_build_npc_section):
      test_s06_character_system.py
  AC-6.6 — Hidden goal influence in NPC dialogue (goals_short in _build_npc_section):
      test_s06_character_system.py
  AC-6.7 — Companion presence in generation (_identify_companions):
      test_s06_character_system.py

v2 ACs (deferred — require engine features not built in v1):
  AC-6.2 — Trait evolution: requires a trait-mutation subsystem that tracks
            contrary-to-trait actions (10+ count), shifts trait values, and
            injects a narrative acknowledgement.  No ``update_trait``,
            trait-count accumulator, or trait-shift logic exists anywhere in
            the v1 codebase (grep: update_trait / trait_shift / trait_change
            → no matches).
  AC-6.10 — NPC death tracking: requires a death-event subsystem that marks
             NPCs as dead, surfaces the death to other NPCs' dialogue contexts,
             and redistributes the dead NPC's narrative functions. The NPC model
             carries an ``alive`` flag but no write path, no death-event emitter,
             and no redistribution logic exist in v1 (grep: npc.*dead/death
             → no matches in pipeline or service layers).
"""

from __future__ import annotations

import pytest

from tta.api.routes.games import _parse_relationship_delta
from tta.models.world import (
    RelationshipChange,
    RelationshipDimensions,
    apply_relationship_change,
)
from tta.pipeline.stages.generate import _build_npc_section
from tta.world.relationship_service import (
    InMemoryRelationshipService,
)

# ── Shared helpers ─────────────────────────────────────────────────────────────


def _fresh_svc() -> InMemoryRelationshipService:
    """Return a new in-memory relationship service."""
    return InMemoryRelationshipService()


# ── AC-6.2: Trait evolution on contrary-to-trait actions (DEFERRED v2) ────────

# No test class — see module docstring for full rationale.
# When the trait-evolution subsystem is implemented, add tests here covering:
#   - TraitCounter.increment returns count per (session_id, npc_id, trait)
#   - At count ≥ 10, evaluate_trait_shift() mutates the NPC's traits list
#   - The narrative output for that turn contains an acknowledgement phrase
#     (e.g. "you seem to have changed", "others notice a shift in you")


# ── AC-6.4: Relationship dimensions increase when player helps an NPC ─────────


@pytest.mark.spec("AC-06.04")
class TestAC604RelationshipHelp:
    """AC-6.4: Helping an NPC increases Trust, Affinity, Respect by appropriate amounts.

    Covers the two testable layers:
      1. _parse_relationship_delta — maps LLM payload dimensions/directions to a
         RelationshipChange with correct delta values.
      2. InMemoryRelationshipService.update_relationship — applies the change and
         returns a record with the expected new dimension values.

    The spec says "context-appropriate amounts". In v1 the step is fixed at ±5
    per interaction for normal events (S06 FR-5.3), plus familiarity += 3 for
    every interaction.
    """

    # ── _parse_relationship_delta ──────────────────────────────────────────────

    def test_positive_trust_direction_yields_plus_five_trust(self) -> None:
        """AC-6.4: Positive trust direction → trust delta = +5, familiarity = +3."""
        change = _parse_relationship_delta(
            {"dimension": "trust", "direction": "increased"}
        )
        assert change.trust == 5
        assert change.familiarity == 3

    def test_positive_affinity_direction_yields_plus_five_affinity(self) -> None:
        """AC-6.4: Positive affinity direction → affinity delta = +5."""
        change = _parse_relationship_delta(
            {"dimension": "affinity", "direction": "grew warmer"}
        )
        assert change.affinity == 5
        assert change.trust == 0

    def test_positive_respect_direction_yields_plus_five_respect(self) -> None:
        """AC-6.4: Positive respect direction → respect delta = +5."""
        change = _parse_relationship_delta(
            {"dimension": "respect", "direction": "positive"}
        )
        assert change.respect == 5
        assert change.trust == 0
        assert change.affinity == 0

    def test_negative_trust_direction_yields_minus_five(self) -> None:
        """AC-6.4: Negative trust direction → trust delta = -5."""
        change = _parse_relationship_delta(
            {"dimension": "trust", "direction": "decreased"}
        )
        assert change.trust == -5
        assert change.familiarity == 3  # familiarity still increments

    def test_negative_affinity_via_cold_keyword(self) -> None:
        """AC-6.4: 'cold' in direction string → negative affinity delta."""
        change = _parse_relationship_delta(
            {"dimension": "affinity", "direction": "cold"}
        )
        assert change.affinity == -5

    def test_fear_positive_direction_yields_positive_fear(self) -> None:
        """AC-6.4: Positive fear direction → fear delta = +5."""
        change = _parse_relationship_delta(
            {"dimension": "fear", "direction": "increased"}
        )
        assert change.fear == 5

    def test_unmapped_dimension_sets_both_trust_and_affinity(self) -> None:
        """AC-6.4: Unknown dimension → generic trust + affinity shift."""
        change = _parse_relationship_delta(
            {"dimension": "bond", "direction": "positive"}
        )
        assert change.trust == 5
        assert change.affinity == 5

    def test_any_interaction_increments_familiarity_by_three(self) -> None:
        """AC-6.4: familiarity += 3 regardless of dimension/direction."""
        for dim in ("trust", "affinity", "respect", "fear", "bond"):
            change = _parse_relationship_delta(
                {"dimension": dim, "direction": "positive"}
            )
            assert change.familiarity == 3, (
                f"dimension '{dim}' did not yield familiarity=3"
            )

    # ── InMemoryRelationshipService round-trip ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_update_creates_relationship_when_absent(self) -> None:
        """AC-6.4: update_relationship creates a new record if none exists."""
        from uuid import uuid4

        svc = _fresh_svc()
        session_id = uuid4()
        change = RelationshipChange(trust=5, familiarity=3)

        rel = await svc.update_relationship(
            session_id, "player", "npc_merchant", change
        )

        assert rel.dimensions.trust == 5
        assert rel.dimensions.familiarity == 3

    @pytest.mark.asyncio
    async def test_helping_npc_increases_trust_round_trip(self) -> None:
        """AC-6.4: After helping event, trust and familiarity exceed baseline."""
        from uuid import uuid4

        svc = _fresh_svc()
        session_id = uuid4()

        # Simulate LLM extracting a 'trust increased' payload
        change = _parse_relationship_delta(
            {"dimension": "trust", "direction": "increased"}
        )
        rel = await svc.update_relationship(session_id, "player", "npc_elder", change)

        assert rel.dimensions.trust > 0, (
            "Trust must increase after positive interaction"
        )
        assert rel.dimensions.familiarity > 0, (
            "Familiarity must increase after any interaction"
        )

    @pytest.mark.asyncio
    async def test_multiple_helps_accumulate_trust(self) -> None:
        """AC-6.4: Repeated positive trust events stack correctly."""
        from uuid import uuid4

        svc = _fresh_svc()
        session_id = uuid4()
        change = RelationshipChange(trust=5, familiarity=3)

        await svc.update_relationship(session_id, "player", "npc_healer", change)
        await svc.update_relationship(session_id, "player", "npc_healer", change)
        rel = await svc.update_relationship(session_id, "player", "npc_healer", change)

        # 3 × trust=5 = 15; each +5 delta is within the per-interaction ±15 clamp,
        # and the accumulated trust value remains well below the overall ±100 bound.
        assert rel.dimensions.trust == 15
        assert rel.dimensions.familiarity == 9

    @pytest.mark.asyncio
    async def test_trust_clamped_at_100(self) -> None:
        """AC-6.4: Trust cannot exceed +100 regardless of repeated positive events."""
        from uuid import uuid4

        svc = _fresh_svc()
        session_id = uuid4()

        # Apply 25 positive-trust events of delta=5 each (would sum to 125)
        change = RelationshipChange(trust=5, familiarity=0)
        rel = await svc.update_relationship(session_id, "player", "npc_ally", change)
        for _ in range(24):  # 24 more = 25 total; rel always bound after first call
            rel = await svc.update_relationship(
                session_id, "player", "npc_ally", change
            )

        assert rel.dimensions.trust == 100, "Trust must be clamped at +100"

    @pytest.mark.asyncio
    async def test_apply_relationship_change_preserves_other_dimensions(self) -> None:
        """AC-6.4: Applying a trust change does not alter respect or fear."""
        dims = RelationshipDimensions(
            trust=10, affinity=20, respect=15, fear=5, familiarity=30
        )
        change = RelationshipChange(trust=5, familiarity=3)
        result = apply_relationship_change(dims, change)

        assert result.trust == 15
        assert result.affinity == 20  # unchanged
        assert result.respect == 15  # unchanged
        assert result.fear == 5  # unchanged
        assert result.familiarity == 33

    @pytest.mark.asyncio
    async def test_companion_eligible_after_sustained_help(self) -> None:
        """AC-6.4: Sufficient trust + affinity unlocks companion eligibility (FR-5.4).

        The companion thresholds are trust > 30 (strictly) and affinity > 20.
        Normal changes are clamped to ±15 (RELATIONSHIP_CLAMP_NORMAL) and
        dramatic changes to ±30.  A single dramatic change of trust=35 is
        clamped to exactly 30, which fails the strict > 30 check.  We
        therefore apply two interactions: one dramatic (trust→30, affinity→25)
        then one normal (trust +5 → 35), simulating sustained positive help.
        """
        from uuid import uuid4

        svc = _fresh_svc()
        session_id = uuid4()

        # First interaction: dramatic positive event (trust→30, affinity→25)
        await svc.update_relationship(
            session_id,
            "player",
            "npc_companion",
            RelationshipChange(trust=35, affinity=25, dramatic=True),
        )
        # Second interaction: normal positive event tips trust above threshold (→35)
        await svc.update_relationship(
            session_id,
            "player",
            "npc_companion",
            RelationshipChange(trust=5),
        )

        eligible = await svc.check_companion_eligible(
            session_id, "player", "npc_companion"
        )
        assert eligible, "NPC with trust>30 and affinity>20 must be companion-eligible"

    @pytest.mark.asyncio
    async def test_not_companion_eligible_below_threshold(self) -> None:
        """AC-6.4: NPC below trust/affinity threshold is NOT companion-eligible."""
        from uuid import uuid4

        svc = _fresh_svc()
        session_id = uuid4()

        # trust=10 (below 30 threshold)
        change = RelationshipChange(trust=10, affinity=10)
        await svc.update_relationship(session_id, "player", "npc_stranger", change)

        eligible = await svc.check_companion_eligible(
            session_id, "player", "npc_stranger"
        )
        assert not eligible


# ── AC-6.8: NPC references shared history on return visit ─────────────────────


@pytest.mark.spec("AC-06.08")
class TestAC608SharedHistory:
    """AC-6.8: NPC references shared history appropriately after a session break.

    In v1 the shared_history field is populated by _inject_shared_history (in
    context_stage) and then rendered by _build_npc_section in the generation
    prompt.  Unit tests here verify the rendering contract of _build_npc_section
    given pre-populated shared_history values.

    The full _inject_shared_history async logic (scanning recent turns from
    turn_repo) is separately verifiable at integration level. We test the
    contract: if shared_history is present in the NPC context dict, _build_npc_section
    must include "History with player:" in its rendered output.
    """

    def test_shared_history_appears_in_npc_section(self) -> None:
        """AC-6.8: NPC section has 'History with player:' when shared_history is set."""
        npc_ctx = [
            {
                "npc_name": "Elder Mirra",
                "shared_history": "Turn 3: Elder Mirra helped find the lost tome.",
            }
        ]
        section = _build_npc_section(npc_ctx)

        assert "History with player:" in section, (
            "_build_npc_section must render 'History with player:' for AC-6.8"
        )
        assert "Elder Mirra helped find the lost tome" in section

    def test_shared_history_excerpt_preserved_verbatim(self) -> None:
        """AC-6.8: The history snippet is passed through unchanged to the prompt."""
        history_text = "Turn 5: You saved Elder Mirra's apprentice from the flood."
        npc_ctx = [{"npc_name": "Elder Mirra", "shared_history": history_text}]

        section = _build_npc_section(npc_ctx)

        assert history_text in section

    def test_multiple_npcs_each_get_own_history(self) -> None:
        """AC-6.8: Each NPC gets their own shared history injected separately."""
        npc_ctx = [
            {
                "npc_name": "Elder Mirra",
                "shared_history": "Turn 2: Elder Mirra taught you the ward-rune.",
            },
            {
                "npc_name": "Captain Steinn",
                "shared_history": "Turn 7: You fought with Steinn at the bridge.",
            },
        ]
        section = _build_npc_section(npc_ctx)

        assert "Elder Mirra taught you the ward-rune" in section
        assert "Steinn at the bridge" in section

    def test_no_history_means_no_history_line(self) -> None:
        """AC-6.8: NPC without shared_history emits no 'History with player:' line."""
        npc_ctx = [{"npc_name": "Unnamed Merchant"}]
        section = _build_npc_section(npc_ctx)

        assert "History with player:" not in section

    def test_empty_string_history_not_rendered(self) -> None:
        """AC-6.8: An empty shared_history string must not produce a history line."""
        npc_ctx = [{"npc_name": "Elder Mirra", "shared_history": ""}]
        section = _build_npc_section(npc_ctx)

        # Empty string is falsy — _build_npc_section uses ctx.get("shared_history")
        assert "History with player:" not in section


# ── AC-6.9: NPC acknowledges knowledge gap authentically ──────────────────────


@pytest.mark.spec("AC-06.09")
class TestAC609KnowledgeBoundary:
    """AC-6.9: NPC response acknowledges knowledge gap (not generic 'I don't know').

    In v1, knowledge boundary is enforced at prompt-instruction level:
      - _build_npc_section renders "  Knows about: {knowledge_boundary}" for
        each NPC that has a knowledge_boundary in its context dict.
      - A footer instruction states "NPCs must not share information outside
        their knowledge boundary."
    These tests verify that both the per-NPC knowledge signal AND the footer
    constraint instruction appear in the rendered section.
    """

    def test_knowledge_boundary_appears_in_npc_section(self) -> None:
        """AC-6.9: 'Knows about:' line rendered when knowledge_boundary is set."""
        npc_ctx = [
            {
                "npc_name": "Scholar Veran",
                "knowledge_boundary": "local herbalism, forest paths, village history",
            }
        ]
        section = _build_npc_section(npc_ctx)

        assert "Knows about:" in section, (
            "_build_npc_section must render 'Knows about:' for AC-6.9"
        )
        assert "local herbalism" in section

    def test_knowledge_boundary_content_preserved(self) -> None:
        """AC-6.9: Knowledge boundary string appears verbatim in prompt section."""
        boundary = "ancient runes, siege tactics, the Thornwood Pact"
        npc_ctx = [{"npc_name": "Archivist Ulm", "knowledge_boundary": boundary}]
        section = _build_npc_section(npc_ctx)

        assert boundary in section

    def test_footer_constraint_always_present(self) -> None:
        """AC-6.9: The 'must not share information outside their knowledge boundary'
        instruction appears in every NPC section regardless of whether individual
        NPCs have knowledge_boundary set."""
        # NPC without explicit knowledge_boundary
        npc_ctx = [{"npc_name": "Innkeeper Breda"}]
        section = _build_npc_section(npc_ctx)

        assert "knowledge boundary" in section.lower(), (
            "Footer constraint 'knowledge boundary' must always appear in NPC section"
        )

    def test_footer_constraint_present_with_knowledge_boundary(self) -> None:
        """AC-6.9: Footer appears even when NPC has an explicit knowledge_boundary."""
        npc_ctx = [
            {
                "npc_name": "Scholar Veran",
                "knowledge_boundary": "only knows local plants",
            }
        ]
        section = _build_npc_section(npc_ctx)

        assert "knowledge boundary" in section.lower()

    def test_no_knowledge_boundary_no_knows_about_line(self) -> None:
        """AC-6.9: Without knowledge_boundary, no 'Knows about:' line is emitted."""
        npc_ctx = [{"npc_name": "Guard Holm"}]
        section = _build_npc_section(npc_ctx)

        assert "Knows about:" not in section

    def test_multiple_npcs_each_get_own_knowledge_boundary(self) -> None:
        """AC-6.9: Each NPC can have a distinct knowledge boundary in the same scene."""
        npc_ctx = [
            {"npc_name": "Scholar Veran", "knowledge_boundary": "forest lore"},
            {
                "npc_name": "Merchant Dara",
                "knowledge_boundary": "trade routes, gold prices",
            },
        ]
        section = _build_npc_section(npc_ctx)

        assert "forest lore" in section
        assert "trade routes, gold prices" in section


# ── AC-6.10: Key NPC death → other NPCs reference death (DEFERRED v2) ─────────

# No test class — see module docstring for full rationale.
# When the NPC death subsystem is implemented, add tests here covering:
#   - Setting npc.alive = False triggers a DEATH world event
#   - Subsequent context_stage enriches other NPCs' dialogue contexts with a
#     "death_acknowledgement" hint naming the deceased NPC
#   - The narrative generation prompt surfaces the death acknowledgement in
#     the NPC section (e.g. "NPC_NAME has died. Others may reference this.")
#   - Dead NPC's narrative functions (quest_giver, merchant, etc.) are
#     redistributed to surviving NPCs in the same region
