#!/usr/bin/env python3
"""TTA v1 simulation harness — multi-turn automated playthrough.

Runs scripted scenarios against a live TTA API and reports pass/fail
with narrative excerpts and timing. Requires a running server stack.

Usage examples::

    uv run python scripts/sim_runner.py
    uv run python scripts/sim_runner.py --scenario tavern
    uv run python scripts/sim_runner.py --quick
    uv run python scripts/sim_runner.py --base-url http://localhost:8000/api/v1
    uv run python scripts/sim_runner.py --json

Pre-requisites::

    docker-compose up -d           # Postgres, Redis, Neo4j
    op run --env-file=.env -- make dev   # API server with LLM keys
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# ── ANSI colours ────────────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def _c(text: str, *codes: str, color: bool = True) -> str:
    if not color:
        return text
    return "".join(codes) + text + RESET


# ── Scenario definitions ─────────────────────────────────────────────────────

SCENARIOS: dict[str, dict[str, Any]] = {
    "tavern": {
        "description": "Explore a tavern — examine, move, and interact",
        "preferences": {"genre": "fantasy", "theme": "tavern"},
        "turns": [
            "look around the tavern carefully",
            "go to the bar and examine the drinks",
            "talk to the bartender about local rumors",
        ],
    },
    "forest": {
        "description": "Explore a forest path — movement and discovery",
        "preferences": {"genre": "fantasy", "theme": "dark forest"},
        "turns": [
            "examine my surroundings",
            "move north along the winding path",
            "pick up the strange object on the ground",
        ],
    },
    "castle": {
        "description": "Medieval castle — diverse intent types",
        "preferences": {"genre": "fantasy", "theme": "medieval castle"},
        "turns": [
            "look around the great hall",
            "examine the ancient throne",
            "open the heavy door to the left",
            "talk to the armored guard",
        ],
    },
    "quick": {
        "description": "Single-turn smoke check",
        "preferences": {"genre": "fantasy"},
        "turns": [
            "look around",
        ],
    },
}

# ── Data models ──────────────────────────────────────────────────────────────


@dataclass
class TurnResult:
    turn_number: int
    player_input: str
    elapsed_ms: float
    event_types: list[str]
    narrative_excerpt: str
    passed: bool
    failure_reason: str = ""


@dataclass
class ScenarioResult:
    name: str
    description: str
    elapsed_s: float
    turn_results: list[TurnResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.turn_results) and all(t.passed for t in self.turn_results)

    @property
    def turns_passed(self) -> int:
        return sum(1 for t in self.turn_results if t.passed)


@dataclass
class SimReport:
    scenarios: list[ScenarioResult] = field(default_factory=list)
    total_elapsed_s: float = 0.0

    @property
    def all_passed(self) -> bool:
        return bool(self.scenarios) and all(s.passed for s in self.scenarios)

    @property
    def scenarios_passed(self) -> int:
        return sum(1 for s in self.scenarios if s.passed)

    @property
    def total_turns(self) -> int:
        return sum(len(s.turn_results) for s in self.scenarios)

    @property
    def turns_passed(self) -> int:
        return sum(s.turns_passed for s in self.scenarios)


# ── SSE stream helpers ────────────────────────────────────────────────────────


def _parse_sse_block(block: str) -> tuple[str, dict[str, Any]]:
    """Parse a single SSE block into (event_type, data_dict)."""
    event_type = "message"
    data_parts: list[str] = []
    for line in block.strip().splitlines():
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_parts.append(line[5:].strip())
    raw = "\n".join(data_parts)
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {"raw": raw}
    return event_type, data


async def _stream_sse(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    timeout: float,
) -> list[tuple[str, dict[str, Any]]]:
    """Stream SSE until turn_complete or timeout. Returns list of (event_type, data)."""
    events: list[tuple[str, dict[str, Any]]] = []
    buffer = ""
    try:
        async with client.stream("GET", url, headers=headers, timeout=timeout) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    if block.strip():
                        event_type, data = _parse_sse_block(block)
                        events.append((event_type, data))
                        if event_type in ("narrative_end", "turn_complete"):
                            return events
    except httpx.TimeoutException:
        pass
    return events


def _extract_narrative(events: list[tuple[str, dict[str, Any]]]) -> str:
    """Concatenate text from narrative chunk events."""
    parts: list[str] = []
    for et, data in events:
        if et == "narrative" and isinstance(data.get("text"), str):
            parts.append(data["text"])
    return " ".join(parts)[:160].replace("\n", " ")


# ── Core sim logic ────────────────────────────────────────────────────────────


async def _register_player(
    client: httpx.AsyncClient, base: str, handle: str
) -> tuple[str, str]:
    """Register an anonymous player, record consent, return (access_token, player_id).

    Flow: POST /auth/anonymous (no body) → PATCH /players/me/consent
    Anonymous players need a separate consent call before they can create games.
    """
    r = await client.post(f"{base}/auth/anonymous")
    if r.status_code != 201:
        raise RuntimeError(f"Player registration failed: {r.status_code} {r.text}")
    data = r.json()["data"]
    token = data["access_token"]
    player_id = data["player_id"]

    # Record consent — required by require_consent dep before game creation
    auth_headers = {"Authorization": f"Bearer {token}"}
    rc = await client.patch(
        f"{base}/players/me/consent",
        json={
            "consent_version": "1.0",
            "consent_categories": {"core_gameplay": True, "llm_processing": True},
            "age_13_plus_confirmed": True,
        },
        headers=auth_headers,
    )
    if rc.status_code not in (200, 204):
        raise RuntimeError(f"Consent recording failed: {rc.status_code} {rc.text}")

    return token, player_id


async def _create_game(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    preferences: dict[str, str],
) -> str:
    """Create a game and return game_id."""
    r = await client.post(
        f"{base}/games",
        json={"preferences": preferences},
        headers=headers,
    )
    if r.status_code != 201:
        raise RuntimeError(f"Game creation failed: {r.status_code} {r.text}")
    return r.json()["data"]["game_id"]


async def _run_turn(
    client: httpx.AsyncClient,
    base: str,
    game_id: str,
    headers: dict[str, str],
    turn_input: str,
    turn_num: int,
    sse_timeout: float,
) -> TurnResult:
    """Submit a turn and stream SSE, returning structured result."""
    t0 = time.monotonic()

    # Submit the turn
    r = await client.post(
        f"{base}/games/{game_id}/turns",
        json={"input": turn_input},
        headers=headers,
    )
    if r.status_code != 202:
        return TurnResult(
            turn_number=turn_num,
            player_input=turn_input,
            elapsed_ms=(time.monotonic() - t0) * 1000,
            event_types=[],
            narrative_excerpt="",
            passed=False,
            failure_reason=f"Turn POST returned {r.status_code}: {r.text[:200]}",
        )

    turn_data = r.json()["data"]
    stream_path = turn_data["stream_url"]
    full_stream_url = f"http://{_host_from_base(base)}{stream_path}"

    # Stream SSE
    events = await _stream_sse(client, full_stream_url, headers, timeout=sse_timeout)
    elapsed_ms = (time.monotonic() - t0) * 1000

    event_types = [et for et, _ in events]

    # Extract narrative excerpt — concatenate text from narrative chunk events
    narrative_excerpt = _extract_narrative(events)

    # Validate required events (S10 FR-10.34/10.35)
    missing = []
    if not any(et == "narrative" for et in event_types):
        missing.append("narrative")
    if "narrative_end" not in event_types:
        missing.append("narrative_end")

    if missing:
        return TurnResult(
            turn_number=turn_num,
            player_input=turn_input,
            elapsed_ms=elapsed_ms,
            event_types=event_types,
            narrative_excerpt=narrative_excerpt,
            passed=False,
            failure_reason=f"Missing required events: {missing}",
        )

    return TurnResult(
        turn_number=turn_num,
        player_input=turn_input,
        elapsed_ms=elapsed_ms,
        event_types=event_types,
        narrative_excerpt=narrative_excerpt,
        passed=True,
    )


def _host_from_base(base: str) -> str:
    """Extract host:port from e.g. http://localhost:8000/api/v1."""
    # Strip scheme and path, return host:port
    without_scheme = base.split("://", 1)[-1]
    host_port = without_scheme.split("/")[0]
    return host_port


async def _run_scenario(
    client: httpx.AsyncClient,
    base: str,
    name: str,
    scenario: dict[str, Any],
    sse_timeout: float,
    verbose: bool,
    color: bool,
) -> ScenarioResult:
    """Run a single scenario end-to-end."""
    t0 = time.monotonic()
    result = ScenarioResult(name=name, description=scenario["description"], elapsed_s=0)

    handle = f"sim-{name}-{secrets.token_hex(3)}"
    try:
        token, _player_id = await _register_player(client, base, handle)
    except Exception as exc:
        # Return a "failed" result with no turns if registration fails
        result.elapsed_s = time.monotonic() - t0
        result.turn_results.append(
            TurnResult(
                turn_number=0,
                player_input="<registration>",
                elapsed_ms=0,
                event_types=[],
                narrative_excerpt="",
                passed=False,
                failure_reason=f"Player registration failed: {exc}",
            )
        )
        return result

    headers = {"Authorization": f"Bearer {token}"}

    try:
        game_id = await _create_game(
            client, base, headers, scenario.get("preferences", {})
        )
    except Exception as exc:
        result.elapsed_s = time.monotonic() - t0
        result.turn_results.append(
            TurnResult(
                turn_number=0,
                player_input="<game_creation>",
                elapsed_ms=0,
                event_types=[],
                narrative_excerpt="",
                passed=False,
                failure_reason=f"Game creation failed: {exc}",
            )
        )
        return result

    for i, turn_input in enumerate(scenario["turns"], start=1):
        if verbose:
            indent = "    "
            print(
                f"{indent}Turn {i}/{len(scenario['turns'])}: "
                f"{_c(repr(turn_input), DIM, color=color)}"
            )

        turn_result = await _run_turn(
            client, base, game_id, headers, turn_input, i, sse_timeout
        )
        result.turn_results.append(turn_result)

        if verbose:
            indent = "      "
            if turn_result.passed:
                evt_str = ", ".join(turn_result.event_types)
                print(
                    f"{indent}{_c('✓', GREEN, BOLD, color=color)} "
                    f"Events: {_c(evt_str, DIM, color=color)} "
                    f"({turn_result.elapsed_ms:.0f}ms)"
                )
                if turn_result.narrative_excerpt:
                    excerpt = turn_result.narrative_excerpt
                    print(f"{indent}  {_c('❝ ' + excerpt + '…', CYAN, color=color)}")
            else:
                print(
                    f"{indent}{_c('✗', RED, BOLD, color=color)} "
                    f"{_c(turn_result.failure_reason, RED, color=color)}"
                )
                if turn_result.event_types:
                    evts = ", ".join(turn_result.event_types)
                    print(f"{indent}  Got events: {_c(evts, DIM, color=color)}")

    result.elapsed_s = time.monotonic() - t0
    return result


# ── Reporting ─────────────────────────────────────────────────────────────────


def _print_report(report: SimReport, color: bool = True) -> None:
    width = 56
    sep = "═" * width

    print()
    print(_c(sep, BOLD, color=color))
    if report.all_passed:
        verdict = _c("SIMULATION COMPLETE — ALL PASSED", GREEN, BOLD, color=color)
    else:
        verdict = _c("SIMULATION COMPLETE — FAILURES DETECTED", RED, BOLD, color=color)
    print(f"  {verdict}")
    print(f"  Scenarios : {report.scenarios_passed}/{len(report.scenarios)} passed")
    print(f"  Turns     : {report.turns_passed}/{report.total_turns} passed")
    print(f"  Total time: {report.total_elapsed_s:.1f}s")
    print(_c(sep, BOLD, color=color))

    if not report.all_passed:
        print()
        print(_c("  Failures:", RED, BOLD, color=color))
        for s in report.scenarios:
            if not s.passed:
                for t in s.turn_results:
                    if not t.passed:
                        print(
                            f"    [{s.name}] Turn {t.turn_number} "
                            f"{_c(repr(t.player_input)[:40], DIM, color=color)}: "
                            f"{_c(t.failure_reason, RED, color=color)}"
                        )
    print()


def _print_json_report(report: SimReport) -> None:
    out: dict[str, Any] = {
        "passed": report.all_passed,
        "scenarios_passed": report.scenarios_passed,
        "scenarios_total": len(report.scenarios),
        "turns_passed": report.turns_passed,
        "turns_total": report.total_turns,
        "total_elapsed_s": round(report.total_elapsed_s, 3),
        "scenarios": [
            {
                "name": s.name,
                "passed": s.passed,
                "elapsed_s": round(s.elapsed_s, 3),
                "turns": [
                    {
                        "number": t.turn_number,
                        "input": t.player_input,
                        "passed": t.passed,
                        "elapsed_ms": round(t.elapsed_ms, 1),
                        "events": t.event_types,
                        "narrative_excerpt": t.narrative_excerpt,
                        "failure_reason": t.failure_reason or None,
                    }
                    for t in s.turn_results
                ],
            }
            for s in report.scenarios
        ],
    }
    print(json.dumps(out, indent=2))


# ── Main ──────────────────────────────────────────────────────────────────────


async def run(
    base: str,
    scenario_names: list[str],
    sse_timeout: float,
    verbose: bool,
    json_output: bool,
    color: bool,
) -> SimReport:
    report = SimReport()
    t0 = time.monotonic()

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Pre-flight health check
        if not json_output:
            print(_c("Pre-flight: checking API readiness…", DIM, color=color))
        try:
            hc_start = time.monotonic()
            r = await client.get(f"{base}/health/ready")
            hc_ms = (time.monotonic() - hc_start) * 1000
            if r.status_code != 200:
                print(
                    _c(
                        f"  ✗ Health check failed: {r.status_code}",
                        RED,
                        BOLD,
                        color=color,
                    )
                )
                print(
                    _c(
                        "  Make sure the server is running: make dev",
                        YELLOW,
                        color=color,
                    )
                )
                sys.exit(1)
            if not json_output:
                print(
                    f"  {_c('✓', GREEN, BOLD, color=color)} API ready ({hc_ms:.0f}ms)"
                )
        except httpx.ConnectError:
            print(
                _c(
                    f"  ✗ Cannot connect to {base}",
                    RED,
                    BOLD,
                    color=color,
                )
            )
            print(
                _c(
                    "  Start the stack first: docker-compose up -d && make dev",
                    YELLOW,
                    color=color,
                )
            )
            sys.exit(1)

        # Run scenarios
        for name in scenario_names:
            scenario = SCENARIOS[name]
            if not json_output:
                bar = "─" * 44
                print()
                print(
                    f"  {_c(f'Scenario: {name}', BOLD, color=color)}  "
                    f"{_c(bar, DIM, color=color)}"
                )
                print(f"    {_c(scenario['description'], DIM, color=color)}")
                print(
                    f"    Turns: {len(scenario['turns'])} | "
                    f"Prefs: {scenario.get('preferences', {})}"
                )
            if verbose and not json_output:
                print()

            s_result = await _run_scenario(
                client, base, name, scenario, sse_timeout, verbose, color
            )
            report.scenarios.append(s_result)

            if not json_output:
                status = (
                    _c("PASSED", GREEN, BOLD, color=color)
                    if s_result.passed
                    else _c("FAILED", RED, BOLD, color=color)
                )
                print(
                    f"  → {status}  "
                    f"{s_result.turns_passed}/{len(s_result.turn_results)} turns  "
                    f"({s_result.elapsed_s:.2f}s)"
                )

    report.total_elapsed_s = time.monotonic() - t0
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TTA v1 simulation harness — scripted multi-turn playthrough.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
available scenarios: {", ".join(SCENARIOS)}

examples:
  uv run python scripts/sim_runner.py
  uv run python scripts/sim_runner.py --scenario tavern
  uv run python scripts/sim_runner.py --quick
  uv run python scripts/sim_runner.py --json > results.json
""",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000/api/v1",
        metavar="URL",
        help="API base URL (default: http://localhost:8000/api/v1)",
    )
    parser.add_argument(
        "--scenario",
        metavar="NAME",
        help=f"Run a single scenario ({', '.join(SCENARIOS)}). Default: all.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run only the 'quick' single-turn scenario.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        metavar="SECS",
        help="SSE stream timeout per turn in seconds (default: 60)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show per-turn event details and narrative excerpts.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output machine-readable JSON report (suppresses console output).",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colour output.",
    )

    args = parser.parse_args()
    color = not args.no_color and sys.stdout.isatty()

    # Determine which scenarios to run
    if args.quick:
        scenario_names = ["quick"]
    elif args.scenario:
        if args.scenario not in SCENARIOS:
            print(
                f"Unknown scenario {args.scenario!r}. "
                f"Available: {', '.join(SCENARIOS)}",
                file=sys.stderr,
            )
            sys.exit(1)
        scenario_names = [args.scenario]
    else:
        # All scenarios except "quick" (quick is explicitly opt-in)
        scenario_names = [k for k in SCENARIOS if k != "quick"]

    if not args.json_output:
        print()
        print(_c("  TTA v1 Simulation Runner", BOLD, color=color))
        print(f"  Scenarios : {', '.join(scenario_names)}")
        print(f"  Base URL  : {args.base_url}")
        print(f"  Timeout   : {args.timeout}s per turn")
        print()

    report = asyncio.run(
        run(
            base=args.base_url,
            scenario_names=scenario_names,
            sse_timeout=args.timeout,
            verbose=args.verbose or not args.json_output,
            json_output=args.json_output,
            color=color,
        )
    )

    if args.json_output:
        _print_json_report(report)
    else:
        _print_report(report, color=color)

    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    main()
