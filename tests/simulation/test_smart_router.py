"""Test smart router with TTA simulation harness."""

import asyncio
from pathlib import Path
from uuid import uuid4

from tta.choices.consequence_service import InMemoryConsequenceService
from tta.genesis.genesis_lite import run_genesis_lite
from tta.llm.smart_router_client import SmartRouterLLMClient
from tta.models.turn import TurnState
from tta.models.world import WorldSeed
from tta.pipeline.orchestrator import run_pipeline
from tta.pipeline.types import PipelineDeps
from tta.safety.hooks import PassthroughHook
from tta.world.memory_service import InMemoryWorldService
from tta.world.template_registry import TemplateRegistry


async def test_with_smart_router():
    """Run a simple turn through the pipeline using smart router."""

    print("=== Testing Smart Router with TTA Simulation ===\n")

    # Setup
    session_id = uuid4()
    llm = SmartRouterLLMClient()
    world_service = InMemoryWorldService()
    template_registry = TemplateRegistry(
        directory=Path(__file__).resolve().parents[2]
        / "src"
        / "tta"
        / "world"
        / "templates"
    )

    from unittest.mock import AsyncMock

    pipeline_deps = PipelineDeps(
        llm=llm,
        world=world_service,
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=PassthroughHook(),
        safety_pre_gen=PassthroughHook(),
        safety_post_gen=PassthroughHook(),
        consequence_service=InMemoryConsequenceService(),
    )

    # Genesis
    print("1. Running genesis...")
    template = template_registry.get("quiet_village")
    seed = WorldSeed(
        template=template,
        tone="mysterious",
        tech_level="medieval",
        magic_presence="low",
        world_scale="village",
        character_name="Test Player",
        character_concept="adventurer",
    )

    await run_genesis_lite(
        session_id=session_id,
        player_id=uuid4(),
        world_seed=seed,
        llm=llm,
        world_service=world_service,
    )
    print("   Genesis complete!")

    # Turn 1: simple
    print("\n2. Running turn 1 (simple)...")
    state1 = TurnState(
        session_id=session_id,
        turn_number=1,
        player_input="look around",
        game_state={"active": True, "turn": 1},
    )
    result1 = await run_pipeline(state1, pipeline_deps)
    print(f"   Status: {result1.status}")
    narr1 = result1.narrative_output[:100] if result1.narrative_output else "none"
    print(f"   Narrative: {narr1}...")

    # Turn 2: coding task
    print("\n3. Running turn 2 (coding task)...")
    llm_coding = SmartRouterLLMClient()
    pipeline_deps_coding = PipelineDeps(
        llm=llm_coding,
        world=world_service,
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=PassthroughHook(),
        safety_pre_gen=PassthroughHook(),
        safety_post_gen=PassthroughHook(),
        consequence_service=InMemoryConsequenceService(),
    )

    state2 = TurnState(
        session_id=session_id,
        turn_number=2,
        player_input="examine the ancient text",
        game_state={"active": True, "turn": 2},
    )
    result2 = await run_pipeline(state2, pipeline_deps_coding)
    print(f"   Status: {result2.status}")
    narr2 = result2.narrative_output[:100] if result2.narrative_output else "none"
    print(f"   Narrative: {narr2}...")

    print("\n=== Test Complete ===")


if __name__ == "__main__":
    from pathlib import Path

    asyncio.run(test_with_smart_router())
