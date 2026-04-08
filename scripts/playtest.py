#!/usr/bin/env python3
"""Interactive CLI playtest for TTA.

Usage:
    uv run python scripts/playtest.py [--base-url URL]

Connects to a running TTA API server, registers a player, creates a game,
and opens an interactive turn loop. SSE narrative is streamed in real-time.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import uuid

import httpx

DEFAULT_BASE = os.getenv("TTA_BASE_URL", "http://localhost:8000/api/v1")
STREAM_TIMEOUT = 120.0


def _color(text: str, code: int) -> str:
    """Wrap text in ANSI color if stdout is a terminal."""
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def _dim(text: str) -> str:
    return _color(text, 2)


def _green(text: str) -> str:
    return _color(text, 32)


def _cyan(text: str) -> str:
    return _color(text, 36)


def _red(text: str) -> str:
    return _color(text, 31)


def _yellow(text: str) -> str:
    return _color(text, 33)


def _parse_sse_lines(
    lines: list[str],
) -> tuple[str | None, str | None]:
    """Parse SSE event type and data from accumulated lines."""
    event_type = None
    data_parts: list[str] = []
    for line in lines:
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_parts.append(line[5:].strip())
    data = "\n".join(data_parts) if data_parts else None
    return event_type, data


def register_player(client: httpx.Client) -> tuple[str, str]:
    """Register an anonymous player. Returns (player_id, token)."""
    handle = f"playtester-{uuid.uuid4().hex[:8]}"
    resp = client.post("/players", json={"handle": handle})
    resp.raise_for_status()
    data = resp.json()["data"]
    return data["player_id"], data["session_token"]


def create_game(client: httpx.Client) -> str:
    """Create a new game session. Returns game_id."""
    resp = client.post("/games", json={})
    resp.raise_for_status()
    return resp.json()["data"]["game_id"]


def submit_turn(client: httpx.Client, game_id: str, text: str) -> str:
    """Submit a turn. Returns stream_url."""
    resp = client.post(
        f"/games/{game_id}/turns",
        json={"input": text},
    )
    resp.raise_for_status()
    return resp.json()["data"]["stream_url"]


def stream_narrative(client: httpx.Client, stream_url: str) -> None:
    """Connect to SSE endpoint and print narrative as it arrives."""
    buf: list[str] = []

    with client.stream("GET", stream_url, timeout=STREAM_TIMEOUT) as resp:
        resp.raise_for_status()
        for raw_line in resp.iter_lines():
            line = (
                raw_line.decode() if isinstance(raw_line, bytes) else raw_line
            ).rstrip("\r\n")

            if not line:
                if buf:
                    event_type, data = _parse_sse_lines(buf)
                    _handle_sse_event(event_type, data)
                    buf.clear()
                continue
            buf.append(line)

        # Flush remaining buffer
        if buf:
            event_type, data = _parse_sse_lines(buf)
            _handle_sse_event(event_type, data)


def _handle_sse_event(event_type: str | None, data: str | None) -> None:
    """Process a single SSE event."""
    if data is None:
        return

    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return

    if event_type == "turn_start":
        turn = payload.get("turn_number", "?")
        print(_dim(f"\n--- Turn {turn} ---"))

    elif event_type in {"narrative", "narrative_block"}:
        text = payload.get("full_text") or payload.get("text", "")
        if text:
            print(f"\n{_cyan(text)}")

    elif event_type == "narrative_token":
        text = payload.get("text", "")
        if text:
            print(_cyan(text), end="", flush=True)

    elif event_type == "turn_complete":
        model = payload.get("model_used", "?")
        latency = payload.get("latency_ms", 0)
        print(_dim(f"\n  [{model} · {latency:.0f}ms]"))

    elif event_type == "error":
        code = payload.get("code", "UNKNOWN")
        msg = payload.get("message", "")
        print(_red(f"\n  Error: {code} — {msg}"))

    elif event_type == "choices":
        choices = payload.get("choices", [])
        if choices:
            print(_yellow("\n  Choices:"))
            for i, c in enumerate(choices, 1):
                label = c.get("text", c.get("label", str(c)))
                print(_yellow(f"    {i}. {label}"))


def main() -> None:
    parser = argparse.ArgumentParser(description="TTA interactive playtest")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE,
        help=f"API base URL (default: {DEFAULT_BASE})",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    # Ctrl+C exits cleanly
    signal.signal(signal.SIGINT, lambda *_: (print("\n\nBye!"), sys.exit(0)))

    print(_green("═" * 60))
    print(_green("  TTA Playtest CLI"))
    print(_green("═" * 60))
    print(_dim(f"  Server: {base_url}\n"))

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        # 1. Register
        print(_dim("Registering player..."), end=" ", flush=True)
        try:
            player_id, token = register_player(client)
        except httpx.HTTPStatusError as e:
            print(_red(f"FAILED: {e.response.status_code} {e.response.text}"))
            sys.exit(1)
        except httpx.ConnectError:
            print(_red(f"FAILED: Cannot connect to {base_url}"))
            print(_dim("  Is the server running? Try: make dev"))
            sys.exit(1)

        print(_green("OK"))
        print(_dim(f"  Player: {player_id}"))

        # Set auth header for all subsequent requests
        client.headers["Authorization"] = f"Bearer {token}"

        # 2. Create game
        print(_dim("Creating game..."), end=" ", flush=True)
        try:
            game_id = create_game(client)
        except httpx.HTTPStatusError as e:
            print(_red(f"FAILED: {e.response.status_code} {e.response.text}"))
            sys.exit(1)
        print(_green("OK"))
        print(_dim(f"  Game: {game_id}\n"))

        print(_green("Ready! Type your actions below. Ctrl+C to quit.\n"))

        # 3. Turn loop
        turn_num = 0
        while True:
            turn_num += 1
            prompt = _green(f"[Turn {turn_num}] > ")
            try:
                user_input = input(prompt)
            except EOFError:
                print("\n\nBye!")
                break

            if not user_input.strip():
                turn_num -= 1
                continue

            # Submit turn
            try:
                stream_url = submit_turn(client, game_id, user_input)
            except httpx.HTTPStatusError as e:
                print(_red(f"  Error: {e.response.status_code} {e.response.text}"))
                turn_num -= 1
                continue

            # Stream narrative
            try:
                stream_narrative(client, stream_url)
            except httpx.HTTPStatusError as e:
                print(_red(f"  Stream error: {e.response.status_code}"))
            except httpx.ReadTimeout:
                print(_red("  Stream timed out."))

            print()  # blank line between turns


if __name__ == "__main__":
    main()
