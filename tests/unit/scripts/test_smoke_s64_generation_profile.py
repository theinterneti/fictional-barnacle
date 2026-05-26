"""Unit coverage for the S64 practical smoke harness."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tta.llm.client import Message, MessageRole
from tta.llm.roles import ModelRole
from tta.llm.serving_profiles import GenerationServingProfile

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "smoke_s64_generation_profile.py"
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "smoke_s64_generation_profile", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.spec("AC-64.01", "AC-64.06")
def test_smoke_script_exists_for_practical_application_gate() -> None:
    assert SCRIPT_PATH.exists()


@pytest.mark.spec("AC-64.01", "AC-64.06")
@pytest.mark.asyncio
async def test_spy_llm_records_generation_profile_kwargs() -> None:
    module = _load_script_module()
    spy = module.SpyLLM()

    response = await spy.generate(
        ModelRole.GENERATION,
        [Message(role=MessageRole.USER, content="look around")],
        generation_profile=GenerationServingProfile.QUALITY,
    )

    assert response.model_used == "spy-llm"
    assert spy.calls[-1]["role"] == ModelRole.GENERATION.value
    assert spy.calls[-1]["generation_profile"] == "quality"


@pytest.mark.spec("AC-64.01", "AC-64.06")
def test_smoke_result_requires_all_practical_boundaries() -> None:
    module = _load_script_module()
    result = module.SmokeResult(
        game_id="00000000-0000-0000-0000-000000000001",
        turn_id="00000000-0000-0000-0000-000000000002",
        api_generation_profile="quality",
        db_generation_profile="quality",
        world_seed_generation_profile="quality",
        turn_status="complete",
        turn_model_used="spy-llm",
        saw_generation_call=True,
        saw_generation_profile="quality",
    )

    result.assert_contract(profile="quality")
