"""Run TTA simulation with Smart Router as LLM backend."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from tta.choices.consequence_service import InMemoryConsequenceService
from tta.genesis.genesis_lite import run_genesis_lite
from tta.llm.smart_router_client import SmartRouterLLMClient
from tta.models.turn import TurnState, TurnStatus
from tta.models.world import WorldSeed
from tta.pipeline.orchestrator import run_pipeline
from tta.pipeline.types import PipelineDeps
from tta.safety.hooks import PassthroughHook
from tta.world.memory_service import InMemoryWorldService
from tta.world.template_registry import TemplateRegistry


async def run_simulation_with_smart_router():
    """Run 10-turn simulation using smart router."""

    print("=== Smart Router Simulation Test ===\n")

    # Setup
    session_id = uuid4()
    llm = SmartRouterLLMClient()
    world_service = InMemoryWorldService()
    template_registry = TemplateRegistry(
        directory=Path(__file__).resolve().parents[3]
        / "src"
        / "tta"
        / "world"
        / "templates"
    )

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
        character_name="Sim Player",
        character_concept="adventurer",
    )

    await run_genesis_lite(
        session_id=session_id,
        player_id=uuid4(),
        world_seed=seed,
        llm=llm,
        world_service=world_service,
    )
    print("   Genesis complete!\n")

    # Run 10 turns
    inputs = [
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
    ]

    results = []
    for i, input_text in enumerate(inputs, 1):
        print(f"Turn {i}: {input_text}")

        state = TurnState(
            session_id=session_id,
            turn_number=i,
            player_input=input_text,
            game_state={"active": True, "turn": i},
        )

        result = await run_pipeline(state, pipeline_deps)
        results.append(result)

        status_str = "✓" if result.status == TurnStatus.complete else "✗"
        print(f"   {status_str} {result.status}")

        if result.narrative_output:
            print(f"   Narrative: {result.narrative_output[:80]}...")
        print()

    # Summary
    completed = sum(1 for r in results if r.status == TurnStatus.complete)
    print("=== Summary ===")
    print(f"Completed: {completed}/10")

    # Show LLM call count
    print(f"LLM calls: {len(llm.call_history)}")

    return results


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run_simulation_with_smart_router())
