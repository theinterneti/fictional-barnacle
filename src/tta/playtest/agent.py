"""PlaytesterAgent — S42 LLM Playtester Agent Harness."""

from __future__ import annotations

import asyncio
import json
import os
import random
import uuid
from typing import TYPE_CHECKING

import httpx

from tta.llm.client import GenerationParams, Message, MessageRole
from tta.llm.roles import ModelRole
from tta.playtest.profile import TasteProfile, get_taste_profile
from tta.playtest.report import Commentary, PlaytestReport, RunStatus, TurnRecord

if TYPE_CHECKING:
    from tta.llm.client import LLMClient

# Environment-configurable constants (FR-42.01, FR-42.04)
PLAYTEST_TURN_TIMEOUT: float = float(os.environ.get("PLAYTEST_TURN_TIMEOUT", "60"))
PLAYTEST_MIN_TURNS: int = int(os.environ.get("PLAYTEST_MIN_TURNS", "5"))
POLL_INTERVAL: float = 1.0
MAX_CONSECUTIVE_TIMEOUTS: int = 3
_TURN_PHASE = "gameplay"


class PlaytesterAgent:
    """LLM agent that plays TTA sessions end-to-end for automated evaluation.

    FR-42.01 — Session lifecycle: setup → run → finish → PlaytestReport.
    FR-42.06 — Reproducible: same run_seed + persona → same player responses.
    FR-42.07 — Stateless: no shared state between parallel agents.
    """

    def __init__(
        self,
        api_base_url: str,
        llm_client: LLMClient,
        llm_model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._api_base_url = api_base_url.rstrip("/")
        self._llm = llm_client
        self._llm_model = llm_model or os.environ.get(
            "PLAYTEST_LLM_MODEL", "gpt-4o-mini"
        )
        self._api_key = api_key
        self._profile: TasteProfile | None = None
        self._persona_id: str = ""
        self._run_seed: int = 0
        self._persona_jitter_seed: int = 0
        self._scenario_seed_id: str = ""
        self._genesis_phases_completed: int = 0
        self._rng: random.Random = random.Random(0)
        self._turns: list[TurnRecord] = []
        self._game_id: str | None = None
        self._run_id: str = str(uuid.uuid4())

    def setup(
        self,
        scenario_seed_id: str,
        persona_id: str,
        run_seed: int,
        persona_jitter_seed: int = 0,
    ) -> None:
        """Initialise run parameters, random state, and taste profile.

        FR-42.01: Must be called before run().
        FR-42.06: Same args produce the same RNG sequence → same player inputs.
        """
        self._scenario_seed_id = scenario_seed_id
        self._persona_id = persona_id
        self._run_seed = run_seed
        self._persona_jitter_seed = persona_jitter_seed
        self._rng = random.Random(run_seed)
        self._profile = get_taste_profile(persona_id, persona_jitter_seed)
        self._turns = []
        self._game_id = None
        self._run_id = str(uuid.uuid4())

    async def run(self) -> PlaytestReport:
        """Play a full session: create game, play PLAYTEST_MIN_TURNS turns.

        Genesis runs server-side during POST /api/v1/games (FR-42.01).
        3 consecutive timeouts → abandoned status (FR-42.04).
        """
        assert self._profile is not None, "Call setup() before run()"
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(
            base_url=self._api_base_url,
            headers=headers,
            timeout=PLAYTEST_TURN_TIMEOUT + 10,
        ) as client:
            resp = await client.post(
                "/api/v1/games",
                json={
                    "world_id": None,
                    "preferences": {},
                    "scenario_seed_id": self._scenario_seed_id or None,
                },
            )
            resp.raise_for_status()
            game_data = resp.json()["data"]
            self._game_id = game_data["game_id"]
            self._genesis_phases_completed = game_data.get(
                "genesis_phases_completed", 7
            )
            current_narrative = game_data.get("narrative_intro", "")

            consecutive_timeouts = 0
            turn_index = 0
            gameplay_turns_completed = 0

            while gameplay_turns_completed < PLAYTEST_MIN_TURNS:
                # Consume RNG once per turn for reproducibility (FR-42.06)
                rng_value = self._rng.random()
                try:
                    result = await asyncio.wait_for(
                        self._execute_turn(
                            client, current_narrative, turn_index, rng_value
                        ),
                        timeout=PLAYTEST_TURN_TIMEOUT,
                    )
                    player_input, narrative_output, commentary = result
                    consecutive_timeouts = 0
                    self._turns.append(
                        TurnRecord(
                            turn_index=turn_index,
                            phase=_TURN_PHASE,
                            player_input=player_input,
                            narrative=narrative_output,
                            commentary=commentary,
                            timed_out=False,
                        )
                    )
                    current_narrative = narrative_output
                    gameplay_turns_completed += 1
                    turn_index += 1
                except TimeoutError:
                    consecutive_timeouts += 1
                    self._turns.append(
                        TurnRecord(
                            turn_index=turn_index,
                            phase=_TURN_PHASE,
                            player_input="",
                            narrative="",
                            commentary=_blank_commentary(turn_index),
                            timed_out=True,
                        )
                    )
                    turn_index += 1
                    if consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
                        return self._build_report("abandoned")

        return await self.finish()

    async def finish(self) -> PlaytestReport:
        """Emit the final PlaytestReport with aggregate rating (FR-42.05)."""
        return self._build_report("complete")

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _execute_turn(
        self,
        client: httpx.AsyncClient,
        narrative: str,
        turn_index: int,
        rng_value: float,
    ) -> tuple[str, str, Commentary]:
        """Generate input, submit to API, poll for narrative, then comment."""
        profile = self._profile
        assert profile is not None

        # Temperature: boldness shifts the distribution, rng adds reproducible noise
        temperature = 0.4 + rng_value * 0.1 + profile.boldness * 0.5
        temperature = min(1.0, max(0.1, temperature))

        player_input = await self._generate_player_input(
            narrative, turn_index, temperature
        )
        narrative_output = await self._submit_and_poll(client, player_input, turn_index)
        commentary = await self._generate_commentary(
            turn_index, narrative, player_input, narrative_output
        )
        return player_input, narrative_output, commentary

    async def _generate_player_input(
        self,
        narrative: str,
        turn_index: int,
        temperature: float,
    ) -> str:
        """Generate player response using the agent's taste profile (FR-42.02)."""
        profile = self._profile
        assert profile is not None

        verbosity_desc = _verbosity_description(profile.verbosity)
        boldness_desc = _boldness_description(profile.boldness)
        system_parts = [
            "You are an automated playtester for a text adventure game.",
            f"Your personality: {verbosity_desc} {boldness_desc}",
            (
                f"Genre preference: {profile.genre_affinity}. "
                f"Tone preference: {profile.tone_affinity}."
            ),
        ]
        if profile.trope_affinity:
            system_parts.append(
                f"You gravitate toward: {', '.join(profile.trope_affinity)}."
            )
        if profile.curiosity > 0.7:
            system_parts.append("You like to ask follow-up questions.")
        if profile.meta_awareness > 0.7:
            system_parts.append("You sometimes comment on game mechanics.")
        # AC-42.04: enforce brevity constraint for very terse personas
        if profile.verbosity <= 0.1:
            system_parts.append("Keep your response under 20 characters.")

        messages = [
            Message(role=MessageRole.SYSTEM, content=" ".join(system_parts)),
            Message(
                role=MessageRole.USER,
                content=(
                    f"[Turn {turn_index}] The game shows:\n\n{narrative}"
                    "\n\nWhat do you do or say?"
                ),
            ),
        ]
        params = GenerationParams(temperature=temperature, max_tokens=256)
        response = await self._llm.generate(
            role=ModelRole.GENERATION,
            messages=messages,
            params=params,
        )
        return response.content.strip()

    async def _submit_and_poll(
        self,
        client: httpx.AsyncClient,
        player_input: str,
        turn_index: int,
    ) -> str:
        """Submit turn to API (202) then poll GET /turns until complete."""
        assert self._game_id is not None
        resp = await client.post(
            f"/api/v1/games/{self._game_id}/turns",
            json={"input": player_input},
        )
        resp.raise_for_status()
        turn_number = resp.json()["data"]["turn_number"]

        while True:
            turns_resp = await client.get(f"/api/v1/games/{self._game_id}/turns")
            turns_resp.raise_for_status()
            for turn in turns_resp.json().get("data", []):
                if turn["turn_number"] == turn_number and turn.get("narrative_output"):
                    return str(turn["narrative_output"])
            await asyncio.sleep(POLL_INTERVAL)

    async def _generate_commentary(
        self,
        turn_index: int,
        prev_narrative: str,
        player_input: str,
        narrative_output: str,
    ) -> Commentary:
        """Generate structured JSON commentary per turn (FR-42.03, OQ-42.03)."""
        prompt = (
            "You are evaluating a text-adventure playtest turn. "
            "Return ONLY valid JSON matching this schema:\n"
            '{"agent_intent":"<str>","surprise_level":<0.0-1.0>,'
            '"surprise_note":"<str>","coherence_rating":<0.0-1.0>,'
            '"coherence_note":"<str>"}\n\n'
            f"PREVIOUS NARRATIVE:\n{prev_narrative}\n\n"
            f"PLAYER INPUT:\n{player_input}\n\n"
            f"NARRATIVE RESPONSE:\n{narrative_output}"
        )
        messages = [Message(role=MessageRole.USER, content=prompt)]
        params = GenerationParams(temperature=0.2, max_tokens=256)
        response = await self._llm.generate(
            role=ModelRole.GENERATION,
            messages=messages,
            params=params,
        )
        return _parse_commentary(turn_index, response.content)

    def _build_report(self, status: RunStatus) -> PlaytestReport:
        completed = [t for t in self._turns if not t.timed_out]
        coherence_scores = [
            t.commentary.coherence_rating for t in completed if t.commentary is not None
        ]
        overall_rating = (
            sum(coherence_scores) / len(coherence_scores) if coherence_scores else 0.0
        )
        return PlaytestReport(
            run_id=self._run_id,
            run_seed=self._run_seed,
            scenario_seed_id=self._scenario_seed_id,
            persona_id=self._persona_id,
            persona_jitter_seed=self._persona_jitter_seed,
            model=self._llm_model,
            status=status,
            genesis_phases_completed=self._genesis_phases_completed,
            gameplay_turns_completed=len(completed),
            turns=list(self._turns),
            overall_agent_rating=round(overall_rating, 4),
            overall_agent_notes="",
        )


# ------------------------------------------------------------------ #
# Module-level helpers                                                 #
# ------------------------------------------------------------------ #


def _verbosity_description(verbosity: float) -> str:
    if verbosity <= 0.1:
        return "You are extremely terse."
    if verbosity <= 0.35:
        return "You are very brief, using short sentences."
    if verbosity <= 0.65:
        return "You write moderate, normal-length responses."
    if verbosity <= 0.85:
        return "You write detailed, paragraph-length responses."
    return "You write elaborate, lengthy responses with rich description."


def _boldness_description(boldness: float) -> str:
    if boldness <= 0.25:
        return "You are very cautious and hesitant."
    if boldness <= 0.5:
        return "You are somewhat cautious."
    if boldness <= 0.75:
        return "You act boldly."
    return "You are extremely impulsive and act immediately."


def _blank_commentary(turn_index: int) -> Commentary:
    return Commentary(
        turn_index=turn_index,
        agent_intent="(turn timed out)",
        surprise_level=0.0,
        surprise_note="",
        coherence_rating=0.0,
        coherence_note="",
    )


def _parse_commentary(turn_index: int, content: str) -> Commentary:
    """Parse LLM JSON commentary; fall back gracefully on parse failure."""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        end = -1 if lines[-1].strip() in ("```", "") else len(lines)
        cleaned = "\n".join(lines[1:end])
    try:
        data = json.loads(cleaned)
        return Commentary(
            turn_index=turn_index,
            agent_intent=str(data.get("agent_intent", "")),
            surprise_level=max(0.0, min(1.0, float(data.get("surprise_level", 0.5)))),
            surprise_note=str(data.get("surprise_note", "")),
            coherence_rating=max(
                0.0, min(1.0, float(data.get("coherence_rating", 0.5)))
            ),
            coherence_note=str(data.get("coherence_note", "")),
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        return Commentary(
            turn_index=turn_index,
            agent_intent=content[:200] if content else "",
            surprise_level=0.5,
            surprise_note="(commentary parse error)",
            coherence_rating=0.5,
            coherence_note="(commentary parse error)",
        )
