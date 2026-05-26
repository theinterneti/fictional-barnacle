#!/usr/bin/env python3
"""Practical S64 generation-profile smoke.

Runs a zero-spend in-process FastAPI flow that exercises the real API boundary,
DB persistence, genesis LLM calls, and turn pipeline LLM routing:

1. anonymous auth + consent
2. POST /api/v1/games with generation_profile
3. POST /api/v1/games/{id}/turns with traffic_class
4. poll persisted turn completion
5. assert API/DB/SpyLLM observed the intended profile and traffic class

This is deliberately a practical application gate, not another unit test.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine

from tta.api.app import create_app
from tta.config import CURRENT_CONSENT_VERSION, Settings, get_settings
from tta.llm.client import GenerationParams, LLMResponse, Message
from tta.llm.roles import ModelRole
from tta.llm.serving_profiles import (
    GenerationServingProfile,
    GenerationTrafficClass,
)
from tta.models.turn import TokenCount


class SmokeResult(BaseModel):
    game_id: str
    turn_id: str
    api_generation_profile: str
    db_generation_profile: str
    world_seed_generation_profile: str
    turn_status: str
    turn_model_used: str
    saw_generation_call: bool
    saw_generation_profile: str | None
    saw_generation_traffic_class: str | None = None

    def assert_contract(
        self,
        *,
        profile: str,
        traffic_class: str | None = None,
    ) -> None:
        assert self.api_generation_profile == profile
        assert self.db_generation_profile == profile
        assert self.world_seed_generation_profile == profile
        assert self.turn_status == "complete"
        assert self.turn_model_used == "spy-llm"
        assert self.saw_generation_call is True
        assert self.saw_generation_profile == profile
        if traffic_class is not None:
            assert self.saw_generation_traffic_class == traffic_class


class NoopSummaryService:
    async def generate_title(self, narrative: str) -> str:
        return "Smoke Harbor"

    async def generate_context_summary(self, turns: list[Any]) -> str:
        return "Smoke harness context summary."


class SpyLLM:
    """No-spend LLM double that records practical routing kwargs."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
        *,
        generation_profile: GenerationServingProfile | None = None,
        traffic_class: GenerationTrafficClass | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "method": "generate",
                "role": role.value,
                "generation_profile": _enum_value(generation_profile),
                "traffic_class": _enum_value(traffic_class),
                "message_count": len(messages),
                "has_response_format": bool(params and params.response_format),
            }
        )
        return _spy_response(role=role, params=params)

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
        *,
        generation_profile: GenerationServingProfile | None = None,
        traffic_class: GenerationTrafficClass | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "method": "stream",
                "role": role.value,
                "generation_profile": _enum_value(generation_profile),
                "traffic_class": _enum_value(traffic_class),
                "message_count": len(messages),
                "has_response_format": bool(params and params.response_format),
            }
        )
        return _spy_response(role=role, params=params)


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    return str(raw)


def _spy_response(*, role: ModelRole, params: GenerationParams | None) -> LLMResponse:
    if role == ModelRole.EXTRACTION and params and params.response_format:
        content = json.dumps(
            {
                "locations": [
                    {
                        "key": "start",
                        "name": "Smoke Harbor",
                        "description": "A practical smoke-test harbor.",
                    }
                ],
                "npcs": [],
                "items": [],
            }
        )
    elif role == ModelRole.EXTRACTION:
        content = json.dumps(
            {
                "intent": "explore",
                "confidence": 0.99,
                "entities": ["harbor"],
                "emotional_tone": "curious",
                "summary": "The player looks around.",
                "world_changes": [],
                "suggested_actions": [
                    "Inspect the pier",
                    "Speak to the watchkeeper",
                    "Follow the lanterns",
                ],
            }
        )
    else:
        content = "Smoke Harbor answers with a lantern-lit path and a useful clue."

    return LLMResponse(
        content=content,
        model_used="spy-llm",
        token_count=TokenCount(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        latency_ms=1.0,
        requested_profile="",
        effective_profile="",
        traffic_class="",
    )


def _load_env_file(path: str | None) -> None:
    if not path:
        return
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _settings_for_smoke() -> Settings:
    base = get_settings()
    return base.model_copy(
        update={
            "environment": "test",
            "llm_mock": True,
            "rate_limit_enabled": False,
            "moderation_enabled": False,
            "otel_enabled": False,
            "langfuse_host": None,
            "langfuse_public_key": None,
            "langfuse_secret_key": None,
        }
    )


def _install_spy_llm(app: Any, spy: SpyLLM) -> None:
    app.state.llm_client = spy
    app.state.pipeline_deps.llm = spy
    app.state.summary_service = NoopSummaryService()


def _run_migrations_if_requested(enabled: bool) -> None:
    if not enabled:
        return
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True)


async def _poll_turn_row(
    *,
    database_url: str,
    turn_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    engine = create_async_engine(database_url)
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            async with engine.connect() as conn:
                result = await conn.execute(
                    sa.text(
                        "SELECT id, status, model_used FROM turns WHERE id = :turn_id"
                    ),
                    {"turn_id": turn_id},
                )
                row = result.mappings().first()
                if row and row["status"] in {"complete", "failed", "moderated"}:
                    return dict(row)
            await asyncio.sleep(0.25)
    finally:
        await engine.dispose()
    raise TimeoutError(f"turn {turn_id} did not finish within {timeout_seconds}s")


async def _fetch_game_row(*, database_url: str, game_id: str) -> dict[str, Any]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                sa.text(
                    "SELECT generation_profile, world_seed FROM game_sessions "
                    "WHERE id = :game_id"
                ),
                {"game_id": game_id},
            )
            row = result.mappings().one()
            return dict(row)
    finally:
        await engine.dispose()


async def run_smoke(
    *,
    profile: str,
    traffic_class: str,
    timeout_seconds: float,
) -> SmokeResult:
    settings = _settings_for_smoke()
    spy = SpyLLM()
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        _install_spy_llm(app, spy)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://s64-smoke.local",
            timeout=timeout_seconds,
        ) as client:
            auth_resp = await client.post("/api/v1/auth/anonymous")
            auth_resp.raise_for_status()
            token = auth_resp.json()["data"]["access_token"]
            client.headers["Authorization"] = f"Bearer {token}"

            consent_resp = await client.patch(
                "/api/v1/players/me/consent",
                json={
                    "consent_version": CURRENT_CONSENT_VERSION,
                    "consent_categories": {
                        "core_gameplay": True,
                        "llm_processing": True,
                    },
                    "age_13_plus_confirmed": True,
                },
            )
            consent_resp.raise_for_status()

            create_resp = await client.post(
                "/api/v1/games",
                json={
                    "world_id": None,
                    "preferences": {
                        "tone": "mysterious",
                        "defining_detail": "a practical smoke test",
                    },
                    "generation_profile": profile,
                },
            )
            create_resp.raise_for_status()
            game_data = create_resp.json()["data"]
            game_id = game_data["game_id"]

            turn_resp = await client.post(
                f"/api/v1/games/{game_id}/turns",
                json={
                    "input": "Look around Smoke Harbor and name one useful clue.",
                    "idempotency_key": str(uuid4()),
                    "traffic_class": traffic_class,
                },
            )
            turn_resp.raise_for_status()
            turn_id = turn_resp.json()["data"]["turn_id"]

            turn_row = await _poll_turn_row(
                database_url=settings.database_url,
                turn_id=turn_id,
                timeout_seconds=timeout_seconds,
            )
            game_row = await _fetch_game_row(
                database_url=settings.database_url,
                game_id=game_id,
            )

    world_seed = game_row["world_seed"]
    if isinstance(world_seed, str):
        world_seed = json.loads(world_seed)
    generation_calls = [
        call for call in spy.calls if call["role"] == ModelRole.GENERATION.value
    ]
    matching_turn_calls = [
        call for call in generation_calls if call.get("traffic_class") == traffic_class
    ]
    observed_call = matching_turn_calls[-1] if matching_turn_calls else None

    result = SmokeResult(
        game_id=str(game_id),
        turn_id=str(turn_id),
        api_generation_profile=game_data["generation_profile"],
        db_generation_profile=str(game_row["generation_profile"]),
        world_seed_generation_profile=str(world_seed.get("generation_profile")),
        turn_status=str(turn_row["status"]),
        turn_model_used=str(turn_row["model_used"]),
        saw_generation_call=observed_call is not None,
        saw_generation_profile=(
            str(observed_call.get("generation_profile")) if observed_call else None
        ),
        saw_generation_traffic_class=(
            str(observed_call.get("traffic_class")) if observed_call else None
        ),
    )
    result.assert_contract(profile=profile, traffic_class=traffic_class)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Practical S64 generation-profile API/DB/LLM smoke"
    )
    parser.add_argument(
        "--profile",
        default="quality",
        choices=["fast", "balanced", "quality"],
    )
    parser.add_argument(
        "--traffic-class",
        default="bulk_eval",
        choices=[
            "interactive_player",
            "interactive_smoke",
            "bulk_eval",
            "quality_benchmark",
        ],
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Optional dotenv file to load before migrations/settings.",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Run `uv run alembic upgrade head` before the smoke.",
    )
    return parser


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _load_env_file(args.env_file)
    _run_migrations_if_requested(args.migrate)
    result = await run_smoke(
        profile=args.profile,
        traffic_class=args.traffic_class,
        timeout_seconds=args.timeout,
    )
    print(result.model_dump_json(indent=2))
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
