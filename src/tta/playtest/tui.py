"""TTA Playtest TUI — Textual-based terminal client for therapeutic text adventures.

Usage:
    uv run python -m tta.playtest.tui    # connects to localhost:8010
"""

from __future__ import annotations

import asyncio
import json
import traceback

import httpx
from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Static


class APIClient:
    """Async HTTP client for TTA API."""

    def __init__(self, base_url: str = "http://localhost:8010/api/v1"):
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
        return self._client

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def auth_anonymous(self) -> dict:
        client = await self._ensure_client()
        resp = await client.post(f"{self.base_url}/auth/anonymous")
        resp.raise_for_status()
        data = resp.json()["data"]
        self.token = data["access_token"]
        return data

    async def accept_consent(self) -> None:
        client = await self._ensure_client()
        resp = await client.patch(
            f"{self.base_url}/players/me/consent",
            json={
                "consent_version": "1.0",
                "consent_categories": {"core_gameplay": True, "llm_processing": True},
                "age_13_plus_confirmed": True,
            },
            headers=self._headers(),
        )
        resp.raise_for_status()

    async def create_game(self) -> dict:
        client = await self._ensure_client()
        resp = await client.post(
            f"{self.base_url}/games", json={}, headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()["data"]

    async def submit_turn(self, game_id: str, text: str) -> dict:
        client = await self._ensure_client()
        resp = await client.post(
            f"{self.base_url}/games/{game_id}/turns",
            json={"input": text},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()["data"]

    async def sse_stream(self, game_id: str):
        """Async generator yielding (event_type, raw_data) tuples from SSE."""
        client = await self._ensure_client()
        headers = self._headers()
        headers["Accept"] = "text/event-stream"
        async with client.stream(
            "GET",
            f"{self.base_url}/games/{game_id}/stream",
            headers=headers,
            timeout=httpx.Timeout(None),
        ) as resp:
            resp.raise_for_status()
            event_type = ""
            data_buffer = ""
            async for line in resp.aiter_lines():
                if line.startswith("event: "):
                    event_type = line[7:].strip()
                elif line.startswith("data: "):
                    data_buffer = line[6:]
                elif line == "":
                    if data_buffer:
                        yield event_type, data_buffer
                    event_type = ""
                    data_buffer = ""

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


class ConnectScreen(Vertical):
    """Initial connection screen."""

    def compose(self) -> ComposeResult:
        yield Static("TTA Playtest", classes="title")
        yield Static(
            "Therapeutic Text Adventure · Terminal Edition", classes="subtitle"
        )
        yield Label("API Base URL")
        yield Input(
            value="http://localhost:8010/api/v1",
            placeholder="http://localhost:8010/api/v1",
            id="api-url",
        )
        with Horizontal(id="connect-actions"):
            yield Button("Connect & Play", variant="primary", id="connect-btn")
        yield Static("", id="connect-status")


class GameScreen(Vertical):
    """Main gameplay screen."""

    def compose(self) -> ComposeResult:
        with Container(id="game-container"):
            yield RichLog(id="narrative", highlight=True, markup=True, wrap=True)
            yield Static("", id="live-token")
            yield Static("", id="choices-display")
            with Horizontal(id="input-row"):
                yield Input(
                    placeholder="What do you do?", id="turn-input", disabled=True
                )
                yield Button("Send", variant="primary", id="send-btn", disabled=True)
        with Container(id="meta-footer"):
            yield Static("", id="meta-text")


class TTAPlaytestApp(App):
    """Terminal playtest client for TTA."""

    CSS = """
    .title {
        text-style: bold; color: $accent;
        content-align: center middle; width: 100%; height: 3;
    }
    .subtitle {
        color: $text-disabled; content-align: center middle;
        width: 100%; margin-bottom: 2;
    }
    #api-url { width: 50; margin: 1 0; }
    #connect-actions { align: center middle; margin-top: 1; }
    #connect-status {
        color: $text-disabled; content-align: center middle;
        margin-top: 1; min-height: 1; height: auto; max-height: 8;
    }
    #game-container { height: 1fr; }
    #narrative {
        height: 1fr; border: solid $panel;
        padding: 0 1; background: $surface;
    }
    #live-token {
        min-height: 1; padding: 0 2; color: $accent;
        background: $surface-lighten-1; display: none;
    }
    #live-token.active { display: block; }
    #choices-display {
        min-height: 0; padding: 1; color: $warning;
        background: $panel; border-top: solid $border; display: none;
    }
    #choices-display.visible { display: block; }
    #input-row { height: 3; border-top: solid $border; align: center middle; }
    #turn-input { width: 1fr; margin-right: 1; }
    #send-btn { min-width: 10; }
    #meta-footer {
        height: 1; background: $panel; border-top: solid $border;
        padding: 0 1; align: center middle;
    }
    #meta-text { color: $text-disabled; text-style: italic; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+q", "quit", "Quit", show=False),
    ]

    api: APIClient | None = None
    game_id: str | None = None
    player_id: str | None = None
    current_turn: int = 0
    _sse_worker_ref: object | None = None
    _token_buffer: str = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ConnectScreen(id="connect-screen")
        yield GameScreen(id="game-screen")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#game-screen", GameScreen).display = False
        self.title = "TTA Playtest"

    # ── Connection ───────────────────────────────────────────

    @on(Button.Pressed, "#connect-btn")
    async def on_connect(self) -> None:
        btn = self.query_one("#connect-btn", Button)
        btn.disabled = True
        url = self.query_one("#api-url", Input).value.strip()
        status = self.query_one("#connect-status", Static)

        status.update("connecting...")
        self.api = APIClient(base_url=url)

        try:
            auth = await self.api.auth_anonymous()
            player_id = auth["player_id"]
            self.player_id = player_id
            status.update(f"player {player_id[:8]}...")

            await self.api.accept_consent()
            status.update("creating world (genesis may take ~30s)...")

            game_data = await self.api.create_game()
            game_id = game_data["game_id"]
            self.game_id = game_id
            narrative_intro = game_data.get("narrative_intro", "")

            # ALL setup before screen switch — errors stay visible
            log = self.query_one("#narrative", RichLog)
            log.clear()
            log.write(f"[dim italic]Player: {player_id}[/]")
            log.write(f"[dim italic]Game: {game_id}[/]")
            if narrative_intro.strip():
                log.write(f"[cyan]{escape(narrative_intro.strip())}[/]")
            log.write("[dim italic]Type your action and press Enter.[/]")

            inp = self.query_one("#turn-input", Input)
            inp.disabled = False
            self.query_one("#send-btn", Button).disabled = False

            self.query_one("#connect-screen", ConnectScreen).display = False
            self.query_one("#game-screen", GameScreen).display = True
            inp.focus()
            self.sub_title = f"Game #{game_id[:8]}"

        except Exception as e:
            tb = traceback.format_exc()
            status.update(f"[red]Failed: {e}\n{tb[-300:]}[/red]")
            btn.disabled = False

    # ── SSE Streaming ────────────────────────────────────────

    @work(exclusive=True, thread=False)
    async def _sse_worker(self) -> None:
        assert self.api and self.game_id
        try:
            async for event_type, data in self.api.sse_stream(self.game_id):
                self._handle_sse_event(event_type, data)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._log(f"[red]Stream error: {e}[/]")

    def _handle_sse_event(self, event_type: str, data: str) -> None:
        try:
            payload = json.loads(data) if data else {}
        except json.JSONDecodeError:
            payload = {}

        match event_type:
            case "narrative":
                text = payload.get("text", "")
                seq = payload.get("sequence", 0)
                if text:
                    if seq == 0:
                        self._token_buffer = text
                    else:
                        self._token_buffer += " " + text
                    live = self.query_one("#live-token", Static)
                    live.update(escape(self._token_buffer))
                    live.add_class("active")

            case "narrative_end":
                if self._token_buffer.strip():
                    self._log(f"[cyan]{escape(self._token_buffer)}[/]")
                self._token_buffer = ""
                live = self.query_one("#live-token", Static)
                live.update("")
                live.remove_class("active")
                self._set_input_enabled(True)

            case "state_update":
                changes = payload.get("changes", [])
                if changes:
                    n = len(changes)
                    self._log(
                        f"[dim italic]({n} world change{'s' if n != 1 else ''})[/]"
                    )

            case "heartbeat":
                pass

            case "error":
                code = payload.get("code", "UNKNOWN")
                msg = payload.get("message", "")
                self._log(f"[red]Error: {code} — {msg}[/]")
                self._set_input_enabled(True)

            case "moderation":
                reason = payload.get("reason", "")
                self._log(f"[yellow]Moderation: {reason}[/]")

            # Legacy events
            case "turn_start":
                self.current_turn = payload.get("turn_number", self.current_turn + 1)
                self._log(f"\n[dim italic]─── Turn {self.current_turn} ───[/]")

            case "narrative_token":
                text = payload.get("text", "")
                if text:
                    self._token_buffer += text
                    live = self.query_one("#live-token", Static)
                    live.update(escape(self._token_buffer))
                    live.add_class("active")

            case "narrative_block":
                text = payload.get("text", "")
                if text:
                    self._token_buffer = text
                    live = self.query_one("#live-token", Static)
                    live.update(escape(text))
                    live.add_class("active")

            case "turn_complete":
                if self._token_buffer.strip():
                    self._log(f"[cyan]{escape(self._token_buffer)}[/]")
                self._token_buffer = ""
                live = self.query_one("#live-token", Static)
                live.update("")
                live.remove_class("active")
                self._set_input_enabled(True)

            case "choices":
                choices = payload.get("choices", [])
                if choices:
                    display = self.query_one("#choices-display", Static)
                    lines = ["[bold]Choices:[/]"]
                    for i, c in enumerate(choices, 1):
                        label = c.get("text") or c.get("label") or str(c)
                        lines.append(f"  [bold]{i}.[/] {label}")
                    display.update("\n".join(lines))
                    display.add_class("visible")

            case "thinking":
                self.sub_title = "thinking..."
            case "still_thinking":
                self.sub_title = "still thinking..."
            case _:
                pass

    # ── UI Helpers ───────────────────────────────────────────

    def _log(self, text: str) -> None:
        try:
            self.query_one("#narrative", RichLog).write(text)
        except Exception:
            pass

    def _set_input_enabled(self, enabled: bool) -> None:
        inp = self.query_one("#turn-input", Input)
        btn = self.query_one("#send-btn", Button)
        inp.disabled = not enabled
        btn.disabled = not enabled
        if enabled:
            inp.focus()
            self.sub_title = f"Game #{self.game_id[:8]}" if self.game_id else ""

    # ── Turn Submission ──────────────────────────────────────

    @on(Button.Pressed, "#send-btn")
    @on(Input.Submitted, "#turn-input")
    async def on_turn_submit(self) -> None:
        inp = self.query_one("#turn-input", Input)
        text = inp.value.strip()
        if not text or inp.disabled:
            return

        inp.value = ""
        self._set_input_enabled(False)
        self.query_one("#choices-display", Static).remove_class("visible")
        self.query_one("#choices-display", Static).update("")
        self.sub_title = "processing..."

        self._log(f"\n[bold white]> {escape(text)}[/]")

        assert self.api and self.game_id
        try:
            await self.api.submit_turn(self.game_id, text)
            self._sse_worker()
        except Exception as e:
            self._log(f"[red]Error: {e}[/]")
            self._set_input_enabled(True)

    # ── Cleanup ──────────────────────────────────────────────

    async def on_unmount(self) -> None:
        if self.api:
            await self.api.close()


def main():
    app = TTAPlaytestApp()
    app.run()


if __name__ == "__main__":
    main()
