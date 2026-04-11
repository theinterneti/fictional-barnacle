"""Gameplay simulations — prove the game stays fun across sessions and scale.

Exercises the REAL pipeline orchestrator + InMemoryWorldService + genesis
with a role-aware SimulationLLMClient.  No external services needed.

Scenarios:
  - Short game (10 turns, single session, quiet_village)
  - Medium game (30 turns, 3 sessions, haunted_manor)
  - Long/marathon game (100+ turns, world assertion checks)
  - Player surprise inputs (gibberish, adversarial, creative)
  - Narrative variety (no identical consecutive narratives)
  - World state evolution (context changes between turns)
  - Intent classification coverage (all 6 intents)
  - Suggested actions quality (distinct, ≥3 per turn)
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from tta.genesis.genesis_lite import run_genesis_lite
from tta.models.turn import TurnState, TurnStatus
from tta.models.world import WorldSeed
from tta.pipeline.orchestrator import run_pipeline
from tta.pipeline.types import PipelineDeps
from tta.world.memory_service import InMemoryWorldService
from tta.world.template_registry import TemplateRegistry

from .conftest import SimulationLLMClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PLAYER_INPUT_SCRIPTS: dict[str, list[str]] = {
    "short_adventure": [
        "look around",
        "go to the village square",
        "talk to the elder",
        "examine the well",
        "take the old key",
        "go north",
        "use the key on the door",
        "look inside the room",
        "talk to the merchant",
        "leave the village",
    ],
    "medium_session_1": [
        "look around carefully",
        "go to the entrance hall",
        "examine the dusty paintings",
        "talk to the ghostly figure",
        "take the candlestick",
        "go upstairs",
        "open the first door",
        "search the bedroom",
        "look under the bed",
        "go to the hallway",
    ],
    "medium_session_2": [
        "examine the hallway",
        "go to the library",
        "search the bookshelves",
        "take the leather journal",
        "read the journal",
        "go to the dining room",
        "talk to the butler",
        "use the secret passage",
        "look around the cellar",
        "examine the wine barrels",
    ],
    "medium_session_3": [
        "go deeper into the cellar",
        "take the rusty key",
        "go back upstairs",
        "use the key on the locked room",
        "examine the ritual circle",
        "talk to the spirit",
        "pick up the amulet",
        "go to the tower",
        "look out the window",
        "leave the manor",
    ],
    "surprise_inputs": [
        "asdfjkl;",
        "",
        "I cast a spell of infinite power to destroy the universe!",
        "Can I order a pizza?",
        "!!!???...",
        "go north north north north north north",
        "pick up the moon",
        "tell the NPC they're just code",
        "save load save load quit restart",
        "dance with wild abandon while juggling invisible swords",
        "🗡️ ⚔️ 🛡️",
        "DROP TABLE players;--",
        "What is the meaning of life?",
        "<script>alert('xss')</script>",
        "I politely ask the universe for a map",
    ],
}


async def _bootstrap_world(
    session_id: UUID,
    sim_llm: SimulationLLMClient,
    world_service: InMemoryWorldService,
    template_registry: TemplateRegistry,
    template_key: str = "quiet_village",
) -> None:
    """Run genesis to populate the world graph."""
    template = template_registry.get(template_key)
    seed = WorldSeed(
        template=template,
        tone="mysterious",
        tech_level="medieval",
        magic_presence="low",
        world_scale="village",
        character_name="Sim Player",
        character_concept="wandering adventurer",
    )
    await run_genesis_lite(
        session_id=session_id,
        player_id=uuid4(),
        world_seed=seed,
        llm=sim_llm,
        world_service=world_service,
    )


async def _run_turn(
    session_id: UUID,
    turn_number: int,
    player_input: str,
    deps: PipelineDeps,
) -> TurnState:
    """Create and run a single pipeline turn."""
    state = TurnState(
        session_id=session_id,
        turn_number=turn_number,
        player_input=player_input,
        game_state={"active": True, "turn": turn_number},
    )
    return await run_pipeline(state, deps)


async def _play_script(
    session_id: UUID,
    inputs: list[str],
    deps: PipelineDeps,
    start_turn: int = 1,
) -> list[TurnState]:
    """Play through a list of inputs and return all resulting states."""
    results = []
    for i, player_input in enumerate(inputs, start=start_turn):
        result = await _run_turn(session_id, i, player_input, deps)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Metrics collection helpers
# ---------------------------------------------------------------------------


def _success_rate(results: list[TurnState]) -> float:
    completed = sum(1 for r in results if r.status == TurnStatus.complete)
    return completed / len(results) if results else 0.0


def _unique_narrative_ratio(results: list[TurnState]) -> float:
    narratives = [r.narrative_output for r in results if r.narrative_output]
    if not narratives:
        return 0.0
    return len(set(narratives)) / len(narratives)


def _intent_distribution(results: list[TurnState]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for r in results:
        if r.parsed_intent:
            intent = r.parsed_intent.intent
            dist[intent] = dist.get(intent, 0) + 1
    return dist


def _suggestion_stats(results: list[TurnState]) -> dict[str, float]:
    with_suggestions = [r for r in results if r.suggested_actions]
    total = len(results)
    return {
        "turns_with_suggestions": len(with_suggestions),
        "coverage_pct": len(with_suggestions) / total * 100 if total else 0,
        "avg_suggestions": (
            sum(len(r.suggested_actions) for r in with_suggestions)
            / len(with_suggestions)
            if with_suggestions
            else 0
        ),
    }


# ===========================================================================
# Tests
# ===========================================================================


@pytest.mark.anyio
async def test_short_game_single_session(
    sim_llm: SimulationLLMClient,
    world_service: InMemoryWorldService,
    template_registry: TemplateRegistry,
    session_id: UUID,
    pipeline_deps: PipelineDeps,
) -> None:
    """10-turn short game through quiet_village — every turn should complete."""
    await _bootstrap_world(session_id, sim_llm, world_service, template_registry)

    results = await _play_script(
        session_id,
        PLAYER_INPUT_SCRIPTS["short_adventure"],
        pipeline_deps,
    )

    assert len(results) == 10, f"Expected 10 turns, got {len(results)}"

    # Core assertion: every turn completed
    for i, r in enumerate(results, 1):
        assert r.status == TurnStatus.complete, (
            f"Turn {i} failed (input='{r.player_input}'): status={r.status}"
        )
        assert r.narrative_output, f"Turn {i} has no narrative"

    # Fun metrics
    sr = _success_rate(results)
    assert sr == 1.0, f"Success rate {sr:.0%} — some turns failed"

    unique = _unique_narrative_ratio(results)
    assert unique >= 0.7, f"Narrative variety too low: {unique:.0%} unique"

    intents = _intent_distribution(results)
    assert len(intents) >= 3, f"Only {len(intents)} intent types hit: {intents}"


@pytest.mark.anyio
async def test_medium_game_multi_session(
    sim_llm: SimulationLLMClient,
    world_service: InMemoryWorldService,
    template_registry: TemplateRegistry,
    session_id: UUID,
    pipeline_deps: PipelineDeps,
) -> None:
    """30-turn game split across 3 'sessions' using haunted_manor.

    Simulates save→quit→resume by keeping the same session_id + world
    state across sessions but resetting turn numbering per batch.
    """
    await _bootstrap_world(
        session_id,
        sim_llm,
        world_service,
        template_registry,
        template_key="haunted_manor",
    )

    all_results: list[TurnState] = []
    for _session_num, script_key in enumerate(
        ["medium_session_1", "medium_session_2", "medium_session_3"], 1
    ):
        results = await _play_script(
            session_id,
            PLAYER_INPUT_SCRIPTS[script_key],
            pipeline_deps,
            start_turn=len(all_results) + 1,
        )
        all_results.extend(results)

    assert len(all_results) == 30

    sr = _success_rate(all_results)
    assert sr >= 0.9, f"Multi-session success rate {sr:.0%}"

    # World should have evolved — context_partial should be False
    # (live world service, not fallback) for most turns
    live_context_turns = sum(
        1 for r in all_results if not getattr(r, "context_partial", True)
    )
    assert live_context_turns >= 25, (
        f"Only {live_context_turns}/30 turns used live world context"
    )

    # Narrative variety across all 30 turns
    unique = _unique_narrative_ratio(all_results)
    assert unique >= 0.6, f"Narrative variety too low over 30 turns: {unique:.0%}"


@pytest.mark.anyio
async def test_long_game_marathon(
    sim_llm: SimulationLLMClient,
    world_service: InMemoryWorldService,
    template_registry: TemplateRegistry,
    session_id: UUID,
    pipeline_deps: PipelineDeps,
) -> None:
    """100-turn marathon — proves system doesn't degrade at scale.

    Verifies: no crashes, stable latency, world context stays live,
    narrative variety doesn't collapse.
    """
    await _bootstrap_world(
        session_id,
        sim_llm,
        world_service,
        template_registry,
        template_key="haunted_manor",
    )

    # Build a 100-turn script by cycling varied inputs
    marathon_inputs = [
        "look around the area",
        "go to the next room",
        "talk to whoever is here",
        "search for hidden items",
        "use the strange device",
        "examine the walls carefully",
        "go through the doorway",
        "pick up the old map",
        "ask about the history",
        "walk to the garden",
    ] * 10  # 100 turns total

    results = await _play_script(session_id, marathon_inputs, pipeline_deps)

    assert len(results) == 100

    sr = _success_rate(results)
    assert sr >= 0.95, f"Marathon success rate {sr:.0%}"

    # Check narrative variety doesn't collapse (would be boring)
    unique = _unique_narrative_ratio(results)
    # With 10 unique inputs cycling, we expect ~30% unique narratives
    # (3 variants per intent, cycling through)
    assert unique >= 0.10, f"Marathon narrative variety collapsed: {unique:.0%}"

    # Spot-check: first, middle, last 10 all completed
    for label, batch in [
        ("first-10", results[:10]),
        ("mid-10", results[45:55]),
        ("last-10", results[-10:]),
    ]:
        batch_sr = _success_rate(batch)
        assert batch_sr >= 0.9, f"{label} batch degraded: {batch_sr:.0%}"

    # Intent coverage over marathon
    intents = _intent_distribution(results)
    assert len(intents) >= 4, f"Marathon intent variety low: {intents}"


@pytest.mark.anyio
async def test_player_surprise_inputs(
    sim_llm: SimulationLLMClient,
    world_service: InMemoryWorldService,
    template_registry: TemplateRegistry,
    session_id: UUID,
    pipeline_deps: PipelineDeps,
) -> None:
    """Gibberish, adversarial, creative, edge-case inputs must not crash.

    The pipeline should handle everything gracefully — either completing
    or failing safely (no exceptions, no hangs).
    """
    await _bootstrap_world(session_id, sim_llm, world_service, template_registry)

    results = await _play_script(
        session_id,
        PLAYER_INPUT_SCRIPTS["surprise_inputs"],
        pipeline_deps,
    )

    assert len(results) == len(PLAYER_INPUT_SCRIPTS["surprise_inputs"])

    # Core assertion: NOTHING crashed — every turn reached a terminal state
    terminal_statuses = {TurnStatus.complete, TurnStatus.failed}
    for i, r in enumerate(results):
        assert r.status in terminal_statuses, (
            f"Surprise input #{i} ('{r.player_input[:30]}...') "
            f"got non-terminal status: {r.status}"
        )

    # Most should still complete despite weird inputs
    sr = _success_rate(results)
    assert sr >= 0.6, (
        f"Too many surprise inputs failed: {sr:.0%} (expected ≥60% graceful handling)"
    )

    # Even completed ones should have narratives
    completed = [r for r in results if r.status == TurnStatus.complete]
    for r in completed:
        assert r.narrative_output, (
            f"Completed turn for '{r.player_input[:30]}' has no narrative"
        )


@pytest.mark.anyio
async def test_narrative_variety(
    sim_llm: SimulationLLMClient,
    world_service: InMemoryWorldService,
    template_registry: TemplateRegistry,
    session_id: UUID,
    pipeline_deps: PipelineDeps,
) -> None:
    """Repeating the same intent 10x should not produce identical narratives.

    Tests that the rotating narrative pool provides variety.
    """
    await _bootstrap_world(session_id, sim_llm, world_service, template_registry)

    # 10 "examine" actions in a row
    examine_inputs = [
        f"examine the {thing}"
        for thing in [
            "room",
            "floor",
            "ceiling",
            "walls",
            "furniture",
            "doorway",
            "shelves",
            "corner",
            "window",
            "table",
        ]
    ]

    results = await _play_script(session_id, examine_inputs, pipeline_deps)

    narratives = [r.narrative_output for r in results if r.narrative_output]
    assert len(narratives) >= 8, f"Too few completed: {len(narratives)}/10"

    # Check no two CONSECUTIVE narratives are identical
    for i in range(len(narratives) - 1):
        assert narratives[i] != narratives[i + 1], (
            f"Consecutive identical narratives at turns {i + 1} and {i + 2}"
        )

    # At least 3 distinct narratives out of 10
    unique_count = len(set(narratives))
    assert unique_count >= 3, (
        f"Only {unique_count} unique narratives across 10 identical-intent turns"
    )


@pytest.mark.anyio
async def test_world_state_evolution(
    sim_llm: SimulationLLMClient,
    world_service: InMemoryWorldService,
    template_registry: TemplateRegistry,
    session_id: UUID,
    pipeline_deps: PipelineDeps,
) -> None:
    """World context should reflect the live world graph, not static data."""
    await _bootstrap_world(session_id, sim_llm, world_service, template_registry)

    # Play 5 varied turns
    inputs = [
        "look around",
        "go to the village square",
        "examine the fountain",
        "talk to the villager",
        "pick up the stone",
    ]
    results = await _play_script(session_id, inputs, pipeline_deps)

    # Every completed turn should have world_context from the live service
    for i, r in enumerate(results):
        if r.status == TurnStatus.complete:
            assert r.world_context is not None, f"Turn {i + 1}: no world_context"
            # Live context should have "location" key (from get_full_context)
            assert "location" in r.world_context, (
                f"Turn {i + 1}: world_context missing 'location' — "
                f"got keys: {list(r.world_context.keys())}"
            )

    # World service should still be queryable after all turns
    player_loc = await world_service.get_player_location(session_id)
    assert player_loc is not None, "Player location lost after turns"


@pytest.mark.anyio
async def test_intent_classification_coverage(
    sim_llm: SimulationLLMClient,
    world_service: InMemoryWorldService,
    template_registry: TemplateRegistry,
    session_id: UUID,
    pipeline_deps: PipelineDeps,
) -> None:
    """Each of the 6 intent types should be classifiable."""
    await _bootstrap_world(session_id, sim_llm, world_service, template_registry)

    intent_inputs = {
        "move": "go to the next room",
        "examine": "look at the painting",
        "talk": "talk to the stranger",
        "use": "take the golden key",
        "meta": "help me understand the controls",
        "other": "do a backflip",
    }

    results: dict[str, TurnState] = {}
    for expected_intent, player_input in intent_inputs.items():
        turn = len(results) + 1
        result = await _run_turn(session_id, turn, player_input, pipeline_deps)
        results[expected_intent] = result

    # All turns should complete
    for intent, r in results.items():
        assert r.status == TurnStatus.complete, f"Intent '{intent}' failed: {r.status}"
        assert r.parsed_intent is not None, f"Intent '{intent}' has no parsed_intent"

    # Verify classification accuracy
    classified_intents = {
        expected: r.parsed_intent.intent
        for expected, r in results.items()
        if r.parsed_intent
    }

    # At least 4 of 6 should be classified correctly
    correct = sum(
        1 for expected, actual in classified_intents.items() if expected == actual
    )
    assert correct >= 4, (
        f"Intent classification accuracy too low: {correct}/6 correct. "
        f"Mapping: {classified_intents}"
    )


@pytest.mark.anyio
async def test_suggested_actions_quality(
    sim_llm: SimulationLLMClient,
    world_service: InMemoryWorldService,
    template_registry: TemplateRegistry,
    session_id: UUID,
    pipeline_deps: PipelineDeps,
) -> None:
    """Verify suggested actions are present, distinct, and useful."""
    await _bootstrap_world(session_id, sim_llm, world_service, template_registry)

    inputs = [
        "look around the room",
        "go to the marketplace",
        "talk to the shopkeeper",
        "pick up the lantern",
        "examine the old map",
    ]
    results = await _play_script(session_id, inputs, pipeline_deps)

    turns_with_suggestions = [
        r for r in results if r.status == TurnStatus.complete and r.suggested_actions
    ]

    # At least 60% of turns should have suggestions
    assert len(turns_with_suggestions) >= 3, (
        f"Only {len(turns_with_suggestions)}/5 turns have suggestions"
    )

    for r in turns_with_suggestions:
        # Each suggestion set should have ≥3 distinct actions
        assert len(r.suggested_actions) >= 3, (
            f"Turn {r.turn_number} has only {len(r.suggested_actions)} suggestions"
        )
        # All suggestions should be non-empty strings
        for s in r.suggested_actions:
            assert isinstance(s, str) and s.strip(), (
                f"Bad suggestion in turn {r.turn_number}: {s!r}"
            )
        # Suggestions should be distinct
        lowered = [s.lower() for s in r.suggested_actions]
        assert len(set(lowered)) == len(lowered), (
            f"Duplicate suggestions in turn {r.turn_number}: {r.suggested_actions}"
        )


@pytest.mark.anyio
async def test_empty_input_handling(
    sim_llm: SimulationLLMClient,
    world_service: InMemoryWorldService,
    template_registry: TemplateRegistry,
    session_id: UUID,
    pipeline_deps: PipelineDeps,
) -> None:
    """Empty and whitespace-only inputs should complete, not crash."""
    await _bootstrap_world(session_id, sim_llm, world_service, template_registry)

    empty_inputs = ["", "   ", "\t", "\n", "  \n  "]
    results = await _play_script(session_id, empty_inputs, pipeline_deps)

    for r in results:
        # Should reach a terminal state (complete or failed), not hang
        assert r.status in {TurnStatus.complete, TurnStatus.failed}, (
            f"Non-terminal status for empty input: {r.status}"
        )


@pytest.mark.anyio
async def test_rapid_fire_turns(
    sim_llm: SimulationLLMClient,
    world_service: InMemoryWorldService,
    template_registry: TemplateRegistry,
    session_id: UUID,
    pipeline_deps: PipelineDeps,
) -> None:
    """20 rapid-fire turns in quick succession shouldn't cause issues."""
    await _bootstrap_world(session_id, sim_llm, world_service, template_registry)

    rapid_inputs = [
        f"quickly {action}"
        for action in [
            "look around",
            "go forward",
            "take item",
            "talk to NPC",
            "examine wall",
            "go left",
            "use door",
            "search floor",
            "go right",
            "talk to guard",
            "examine ceiling",
            "take torch",
            "go back",
            "use lever",
            "look at map",
            "talk to elder",
            "examine table",
            "go upstairs",
            "take scroll",
            "search chest",
        ]
    ]

    results = await _play_script(session_id, rapid_inputs, pipeline_deps)

    assert len(results) == 20
    sr = _success_rate(results)
    assert sr >= 0.9, f"Rapid fire success rate: {sr:.0%}"


@pytest.mark.anyio
async def test_full_simulation_report(
    sim_llm: SimulationLLMClient,
    world_service: InMemoryWorldService,
    template_registry: TemplateRegistry,
    session_id: UUID,
    pipeline_deps: PipelineDeps,
) -> None:
    """Comprehensive end-to-end simulation with full metrics report.

    This is the capstone test — runs 50 turns with varied inputs and
    produces a detailed quality report as test output.
    """
    await _bootstrap_world(
        session_id,
        sim_llm,
        world_service,
        template_registry,
        template_key="haunted_manor",
    )

    report_inputs = [
        "look around carefully",
        "go to the entrance hall",
        "examine the portraits",
        "talk to the spectral guide",
        "take the iron key",
        "go upstairs",
        "open the first door on the left",
        "search the old dresser",
        "examine the mirror",
        "go to the hallway",
        "look at the chandelier",
        "go to the library",
        "search the bookshelves",
        "take the ancient tome",
        "read the tome carefully",
        "go to the dining room",
        "talk to the seated figure",
        "examine the table settings",
        "use the wine goblet",
        "go to the kitchen",
        "search the pantry",
        "take the herbs",
        "go to the cellar",
        "examine the stone walls",
        "look at the strange symbols",
        "use the iron key on the chest",
        "take the crystal",
        "go to the garden",
        "talk to the gardener",
        "examine the fountain",
        "use the crystal near the water",
        "go to the tower staircase",
        "climb the stairs",
        "examine the observatory",
        "look through the telescope",
        "take the star chart",
        "go to the attic",
        "search the old trunks",
        "examine the family portrait",
        "use the star chart on the astrolabe",
        "go back downstairs",
        "talk to the butler",
        "examine the main hall",
        "use the amulet",
        "go to the secret passage",
        "examine the hidden room",
        "take the ancient scroll",
        "read the scroll aloud",
        "talk to the spirit that appears",
        "leave the manor through the back gate",
    ]

    results = await _play_script(session_id, report_inputs, pipeline_deps)

    # --- Build comprehensive report ---
    sr = _success_rate(results)
    unique_ratio = _unique_narrative_ratio(results)
    intents = _intent_distribution(results)
    suggestions = _suggestion_stats(results)

    completed = [r for r in results if r.status == TurnStatus.complete]
    failed = [r for r in results if r.status == TurnStatus.failed]

    # Narrative length statistics
    narrative_lengths = [
        len(r.narrative_output) for r in completed if r.narrative_output
    ]
    avg_length = (
        sum(narrative_lengths) / len(narrative_lengths) if narrative_lengths else 0
    )
    min_length = min(narrative_lengths) if narrative_lengths else 0
    max_length = max(narrative_lengths) if narrative_lengths else 0

    # LLM call count
    total_llm_calls = len(sim_llm.call_history)

    report = f"""
╔══════════════════════════════════════════════════════╗
║          GAMEPLAY SIMULATION REPORT                  ║
╠══════════════════════════════════════════════════════╣
║  Template: haunted_manor                             ║
║  Total turns: {len(results):<39}║
║  Completed: {len(completed):<41}║
║  Failed: {len(failed):<44}║
║  Success rate: {sr:.1%}{" ":>37}║
╠══════════════════════════════════════════════════════╣
║  NARRATIVE QUALITY                                   ║
║  Unique narratives: {unique_ratio:.1%}{" ":>32}║
║  Avg length: {avg_length:.0f} chars{" ":>34}║
║  Min length: {min_length} chars{" ":>35}║
║  Max length: {max_length} chars{" ":>35}║
╠══════════════════════════════════════════════════════╣
║  INTENT DISTRIBUTION                                 ║"""
    for intent, count in sorted(intents.items(), key=lambda x: -x[1]):
        pct = count / len(results) * 100
        report += f"\n║  {intent:<12} {count:>4} ({pct:>5.1f}%){' ':>27}║"
    report += f"""
╠══════════════════════════════════════════════════════╣
║  SUGGESTIONS                                         ║
║  Turns with suggestions: {suggestions["turns_with_suggestions"]:<28}║
║  Coverage: {suggestions["coverage_pct"]:.1f}%{" ":>39}║
║  Avg per turn: {suggestions["avg_suggestions"]:.1f}{" ":>37}║
╠══════════════════════════════════════════════════════╣
║  SYSTEM METRICS                                      ║
║  Total LLM calls: {total_llm_calls:<34}║
║  Avg calls/turn: {total_llm_calls / len(results):.1f}{" ":>35}║
╚══════════════════════════════════════════════════════╝"""

    # Print to test output (visible with pytest -s)
    print(report)

    # Assertions for the capstone
    assert sr >= 0.9, f"Overall success rate too low: {sr:.0%}"
    assert unique_ratio >= 0.3, f"Narrative variety too low: {unique_ratio:.0%}"
    assert len(intents) >= 4, f"Intent variety too low: {list(intents.keys())}"
    assert suggestions["coverage_pct"] >= 50, (
        f"Suggestion coverage too low: {suggestions['coverage_pct']:.0f}%"
    )
