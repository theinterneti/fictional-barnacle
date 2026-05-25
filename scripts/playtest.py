#!/usr/bin/env python3
"""TTA Playtest CLI — quick interactive playtest session."""

import asyncio
import json
import os
import sys

import httpx
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

TTA_URL = os.getenv("TTA_URL", "http://localhost:8010")
API = f"{TTA_URL}/api/v1"
TIMEOUT = 120

console = Console()


async def api(client, method, path, body=None):
    """Call the TTA API and return parsed JSON data."""
    kwargs = {"timeout": TIMEOUT}
    if body is not None:
        kwargs["json"] = body
    resp = await client.request(method, f"{API}{path}", **kwargs)
    if not resp.is_success:
        console.print(f"[red]API error {resp.status_code}: {resp.text[:200]}[/red]")
        sys.exit(1)
    return resp.json()["data"]


async def stream_sse(client, game_id, token):
    """Stream SSE events and print narrative chunks."""
    url = f"{API}/games/{game_id}/stream"
    headers = {"Authorization": f"Bearer {token}"}
    current_event = None
    current_data = ""

    async with client.stream("GET", url, headers=headers, timeout=None) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                current_event = line[6:].strip()
            elif line.startswith("data:"):
                current_data = line[5:].strip()
            elif line == "" and current_event:
                _handle_sse(current_event, current_data)
                if current_event == "narrative_end":
                    return
                current_event = None
                current_data = ""


def _handle_sse(event_type, data):
    """Parse and display an SSE event."""
    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, TypeError):
        payload = {}

    if event_type == "narrative":
        console.print(payload.get("text", ""), end="", highlight=False)
    elif event_type == "narrative_end":
        console.print()
    elif event_type == "error":
        console.print(f"[yellow]{payload.get('message', 'SSE error')}[/yellow]")
    elif event_type == "heartbeat":
        pass
    elif event_type == "narrative_block":
        console.print(Markdown(payload.get("text", "")))


async def main():
    console.print("[bold cyan]TTA Playtest CLI[/bold cyan]")
    console.print(f"API: {TTA_URL}\n")

    async with httpx.AsyncClient() as client:
        # 1. Create anonymous player
        with console.status("Creating player..."):
            auth = await api(client, "POST", "/auth/anonymous")
        token = auth["access_token"]
        pid = auth["player_id"]
        console.print(f"[green]Player: {pid}[/green]")

        # 2. Accept consent
        with console.status("Accepting consent..."):
            await api(
                client,
                "PATCH",
                "/players/me/consent",
                {
                    "consent_version": "1.0",
                    "consent_categories": {
                        "core_gameplay": True,
                        "llm_processing": True,
                    },
                    "age_13_plus_confirmed": True,
                },
            )
        console.print("[green]Consent accepted[/green]")

        # 3. Create game
        with console.status("Creating game..."):
            game = await api(
                client,
                "POST",
                "/games",
                {
                    "preferences": {"tone": "adventurous", "genre": "fantasy"},
                },
            )
        game_id = game["game_id"]
        console.print(f"[green]Game: {game_id}[/green]")

        # Show narrative intro
        intro = game.get("narrative_intro")
        if intro:
            console.print()
            console.print(Markdown(intro))
            console.print()

        turn_count = game.get("turn_count", 0)
        console.print(f"[dim]Turns played: {turn_count}[/dim]")
        console.print(
            "[dim]Commands: /save /status /character /relationships /end /quit[/dim]"
        )
        console.print()

        # 4. Turn loop
        while True:
            try:
                text = Prompt.ask("[bold]>[/bold]")
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dimmer]Goodbye.[/dimmer]")
                break

            if not text.strip():
                continue
            if text.strip() == "/quit":
                break

            # Slash commands
            if text.strip().startswith("/"):
                result = await api(
                    client,
                    "POST",
                    f"/games/{game_id}/turns",
                    {
                        "input": text.strip(),
                    },
                )
                msg = result.get("message", str(result))
                console.print(Markdown(msg))
                continue

            # Normal turn — submit then stream narrative in real-time
            await api(client, "POST", f"/games/{game_id}/turns", {"input": text})
            await stream_sse(client, game_id, token)
            console.print()


if __name__ == "__main__":
    asyncio.run(main())
