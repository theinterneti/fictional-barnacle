#!/usr/bin/env python3
"""LLM-as-Player: Have an LLM play and reflect on the experience.

Usage:
    uv run python scripts/llm_player.py [--turns N] [--persona NAME]

This creates a real game session, has the LLM play it, and after each turn
asks the LLM to reflect on: coherence, engagement, and fun.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from tta.choices.consequence_service import InMemoryConsequenceService
from tta.genesis.genesis_lite import run_genesis_lite
from tta.llm.client import Message, MessageRole
from tta.llm.roles import ModelRole
from tta.llm.smart_router_client import SmartRouterLLMClient
from tta.models.turn import TurnState
from tta.models.world import WorldSeed
from tta.pipeline.orchestrator import run_pipeline
from tta.pipeline.types import PipelineDeps
from tta.prompts.loader import FilePromptRegistry
from tta.safety.hooks import PassthroughHook
from tta.world.memory_service import InMemoryWorldService
from tta.world.template_registry import TemplateRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]


PERSONAS = {
    "curious": "You are a curious explorer who examines everything thoroughly.",
    "bold": "You are a bold adventurer who acts quickly and takes risks.",
    "cautious": "You are a cautious player who thinks before acting.",
    "social": "You are a social player who prefers talking to NPCs.",
    "explorer": "You are an explorer who loves moving to new locations.",
}


def build_player_prompt(persona: str, turn_history: list[dict]) -> str:
    history_text = ""
    if turn_history:
        history_text = "\n\n--- Previous turns ---\n"
        for h in turn_history[-3:]:
            history_text += f"You: {h['player_input']}\n"
            narrative = (
                h["narrative"][:200] + "..."
                if len(h.get("narrative", "")) > 200
                else h.get("narrative", "")
            )
            history_text += f"Narrative: {narrative}\n"

    base = PERSONAS.get(persona, PERSONAS["curious"])

    return f"""{base}

Your goal is to play a text adventure game. After each turn, you will reflect on:
1. COHERENCE: Did the narrative follow logically from your action?
2. ENGAGEMENT: Were you drawn into the story?
3. FUN: Did you enjoy that turn?

{history_text}
"""


EVALUATION_QUESTIONS = [
    {
        "id": "coherence",
        "question": "Did the narrative follow logically from your action?",
        "aspect": "Narrative Coherence",
        "weight": 1.0,
    },
    {
        "id": "immersion",
        "question": "Were you drawn into the story? Did you feel present in the world?",
        "aspect": "Immersion",
        "weight": 1.0,
    },
    {
        "id": "agency",
        "question": "Did your choices feel meaningful? Did they impact the story?",
        "aspect": "Player Agency",
        "weight": 1.2,
    },
    {
        "id": "world_logic",
        "question": (
            "Did the world follow consistent rules? "
            "Did NPCs behave believably?"
        ),
        "aspect": "World Consistency",
        "weight": 0.8,
    },
    {
        "id": "pacing",
        "question": "Was the pacing good? Too fast, too slow, or just right?",
        "aspect": "Pacing",
        "weight": 0.8,
    },
    {
        "id": "character",
        "question": (
            "Did you feel like a character in a story, "
            "or just a user typing commands?"
        ),
        "aspect": "Character Investment",
        "weight": 1.0,
    },
    {
        "id": "discovery",
        "question": "Did you want to keep exploring? Was there always something new?",
        "aspect": "Discovery & Curiosity",
        "weight": 0.8,
    },
    {
        "id": "emotion",
        "question": (
            "Did any moment make you feel something? "
            "(curious, tense, amused, wonder)"
        ),
        "aspect": "Emotional Response",
        "weight": 1.0,
    },
]


async def get_llm_reflection(
    llm: SmartRouterLLMClient,
    persona: str,
    player_input: str,
    narrative: str,
    turn_history: list[dict],
) -> dict:
    """Ask the LLM to reflect on this turn with comprehensive evaluation."""

    # Build questions into prompt
    questions_text = ""
    for q in EVALUATION_QUESTIONS:
        questions_text += f"{q['id']}: {q['question']}\n"

    prompt = f"""You are playing a text adventure game as a {persona} player.

Just now, you typed: "{player_input}"

The game responded with:
{narrative[:600]}

Please evaluate this turn. For each question, give a score 0-10 and a brief note.

{questions_text}

Respond in this JSON format (one entry per question):
{{"evaluations": [{{"id": "coherence", "score": 7, "note": "brief"}}, ...]}}
"""

    messages = [
        Message(
            role=MessageRole.SYSTEM, content="You are an analytical game reviewer."
        ),
        Message(role=MessageRole.USER, content=prompt),
    ]

    try:
        resp = await llm.generate(ModelRole.EXTRACTION, messages)
        # Try to parse JSON from response
        content = resp.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        parsed = json.loads(content.strip())
        return parsed.get("evaluations", [])
    except Exception as e:
        # Return defaults
        return [
            {"id": q["id"], "score": 5, "note": f"Parse error: {e}"}
            for q in EVALUATION_QUESTIONS
        ]


async def main():
    parser = argparse.ArgumentParser(description="LLM-as-Player evaluation")
    parser.add_argument("--turns", type=int, default=5, help="Number of turns")
    parser.add_argument("--persona", default="curious", choices=list(PERSONAS.keys()))
    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print(f"LLM-AS-PLAYER: Evaluating TTA with {args.persona} persona")
    print(f"{'=' * 60}\n")

    # Setup
    session_id = uuid4()
    llm = SmartRouterLLMClient()
    world_service = InMemoryWorldService()
    template_registry = TemplateRegistry(
        directory=REPO_ROOT / "src" / "tta" / "world" / "templates"
    )
    prompt_registry = FilePromptRegistry(
        templates_dir=REPO_ROOT / "prompts" / "templates",
        fragments_dir=REPO_ROOT / "prompts" / "fragments",
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
        prompt_registry=prompt_registry,
    )

    # Genesis
    print("1. GENESIS")
    print("-" * 40)
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

    result = await run_genesis_lite(
        session_id=session_id,
        player_id=uuid.uuid4(),
        world_seed=seed,
        llm=llm,
        world_service=world_service,
    )

    print(f"World created: {result.world_id}")
    print(f"Location: {result.player_location_id}")
    intro = result.narrative_intro or "No intro generated."
    print(f"Intro (first 200 chars): {intro[:200]}...")
    print()

    # Track scores
    turn_history = []
    all_scores: dict[str, list[float]] = {q["id"]: [] for q in EVALUATION_QUESTIONS}

    # Player "brain" - uses the same LLM to decide what to do
    async def get_player_input(
        turn_num: int, narrative: str, history: list[dict]
    ) -> str:
        """Have the LLM decide what to do based on persona."""

        prompt = f"""You are playing a text adventure game. {PERSONAS[args.persona]}

The game world so far:
{narrative[:400]}

What do you do? Respond with just your action/command (keep it short, 3-8 words).
Example: "look around carefully" or "talk to the merchant" or "go to the square"
"""

        messages = [
            Message(role=MessageRole.SYSTEM, content=prompt),
            Message(role=MessageRole.USER, content="Decide your next action:"),
        ]

        resp = await llm.generate(ModelRole.GENERATION, messages)
        # Extract action - take first line
        action = resp.content.strip().split("\n")[0][:100]
        return action

    # Gameplay turns
    for turn_num in range(1, args.turns + 1):
        print(f"\n2. TURN {turn_num}")
        print("-" * 40)

        # Get LLM's decision
        last_narrative = turn_history[-1]["narrative"] if turn_history else intro
        player_input = await get_player_input(turn_num, last_narrative, turn_history)
        print(f"Player: {player_input}")

        # Run turn
        state = TurnState(
            session_id=session_id,
            turn_number=turn_num,
            player_input=player_input,
            game_state={"active": True, "turn": turn_num},
        )
        turn_result = await run_pipeline(state, pipeline_deps)

        narrative = turn_result.narrative_output or "No narrative generated."
        print(f"Narrative: {narrative[:200]}...")

        # Get reflection
        reflection = await get_llm_reflection(
            llm, args.persona, player_input, narrative, turn_history
        )

        print("\n📊 Reflection:")
        if isinstance(reflection, list):
            for r in reflection:
                print(
                    "   "
                    f"{r.get('id', '?'):12s}: {r.get('score', '?')}/10 — "
                    f"{r.get('note', '')[:50]}"
                )
        else:
            print(f"   Coherence: {reflection.get('coherence', '?')}/10")
            print(f"   Engagement: {reflection.get('engagement', '?')}/10")
            print(f"   Fun: {reflection.get('fun', '?')}/10")

        turn_history.append(
            {
                "turn": turn_num,
                "player_input": player_input,
                "narrative": narrative,
                "reflection": reflection,
            }
        )

        # Accumulate scores
        if isinstance(reflection, list):
            for r in reflection:
                qid = r.get("id")
                if qid in all_scores:
                    all_scores[qid].append(float(r.get("score", 5)))
        else:
            all_scores["coherence"].append(float(reflection.get("coherence", 5)))
            all_scores["engagement"].append(float(reflection.get("engagement", 5)))
            all_scores["fun"].append(float(reflection.get("fun", 5)))

    # Summary
    print(f"\n{'=' * 60}")
    print("FINAL EVALUATION")
    print(f"{'=' * 60}")

    print(f"\nPersona: {args.persona}")
    print(f"Turns played: {args.turns}")
    print("\n📈 Average Scores:")

    weighted_sum = 0.0
    total_weight = 0.0
    for q in EVALUATION_QUESTIONS:
        qid = q["id"]
        scores = all_scores.get(qid, [])
        if scores:
            avg = sum(scores) / len(scores)
            print(f"   {q['aspect']:20s}: {avg:.1f}/10 (weight: {q['weight']})")
            weighted_sum += avg * q["weight"]
            total_weight += q["weight"]

    overall = weighted_sum / total_weight if total_weight > 0 else 0
    print(f"\n🎯 WEIGHTED OVERALL: {overall:.1f}/10")

    if overall >= 7:
        print("\n✅ VERDICT: The game is fun!")
    elif overall >= 5:
        print("\n⚠️ VERDICT: Decent, but needs work")
    else:
        print("\n❌ VERDICT: Needs improvement")

    return overall


if __name__ == "__main__":
    from uuid import uuid4

    asyncio.run(main())
