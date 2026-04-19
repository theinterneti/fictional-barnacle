"""S28 AC-28.04 — Locust load test harness.

Scenario:
  1. Register a unique anonymous player (with consent)
  2. Create a game
  3. Repeatedly submit turns and consume SSE until turn_complete

Usage (via Makefile):
  make load-test                    # headless, 10 VU, 60s
  uv run locust -f scripts/load_test.py --web-ui  # interactive UI

Environment:
  LLM_MOCK=true must be set in the server environment so no real
  LLM calls are made. Start the server with:
    LLM_MOCK=true uv run python -m tta

Pass/fail criteria (AC-28.04):
  - p95 turn latency <= 2 000 ms
  - error rate < 1 %
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Generator

from locust import HttpUser, between, events, task
from locust.env import Environment as LocustEnv

# ── Config ────────────────────────────────────────────────────────────────────

BASE = "/api/v1"
P95_BUDGET_MS = 2_000  # AC-28.04: p95 must be ≤ 2 s
MAX_ERROR_PCT = 1.0  # AC-28.04: error rate must be < 1 %

PLAYER_INPUTS = [
    "I look around the room carefully.",
    "I pick up the lantern and examine it.",
    "I try the door to the north.",
    "I call out into the darkness.",
    "I search the shadows for anything useful.",
]

CONSENT_PAYLOAD = {
    "consent_version": "1.0",
    "consent_categories": {
        "core_gameplay": True,
        "llm_processing": True,
    },
    "age_confirmed": True,
}


# ── SSE helper ────────────────────────────────────────────────────────────────


def _consume_sse(stream_url: str, client: HttpUser) -> Generator[str, None, None]:
    """Iterate SSE lines from a streaming endpoint until turn_complete."""
    with client.client.get(
        stream_url,
        stream=True,
        catch_response=True,
        name="GET /stream",
        headers={"Accept": "text/event-stream"},
        timeout=30,
    ) as resp:
        if resp.status_code != 200:
            resp.failure(f"SSE stream returned {resp.status_code}")
            return
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw if isinstance(raw, str) else raw.decode()
            if line.startswith("data:"):
                payload = line[5:].strip()
                yield payload
                if '"turn_complete"' in payload or '"event":"turn_complete"' in payload:
                    resp.success()
                    return
        resp.success()


# ── Locust user ───────────────────────────────────────────────────────────────


class TtaUser(HttpUser):
    """Simulates one player: register → create game → repeated turns."""

    wait_time = between(0.5, 1.5)

    game_id: str | None = None
    auth_token: str | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def on_start(self) -> None:
        """Register a player and create a game before running turn tasks."""
        handle = f"load-{secrets.token_hex(6)}"
        payload = {"handle": handle, **CONSENT_PAYLOAD}

        with self.client.post(
            f"{BASE}/players",
            json=payload,
            catch_response=True,
            name="POST /players",
        ) as resp:
            if resp.status_code == 201:
                data = resp.json()["data"]
                self.auth_token = data["session_token"]
                resp.success()
            else:
                resp.failure(f"Registration failed: {resp.status_code} {resp.text}")
                return

        headers = {"Authorization": f"Bearer {self.auth_token}"}

        with self.client.post(
            f"{BASE}/games",
            json={"preferences": {"theme": "fantasy"}},
            headers=headers,
            catch_response=True,
            name="POST /games",
        ) as resp:
            if resp.status_code == 201:
                self.game_id = resp.json()["data"]["game_id"]
                resp.success()
            else:
                resp.failure(f"Game creation failed: {resp.status_code} {resp.text}")

    # ── Main task ──────────────────────────────────────────────────────────

    @task
    def submit_turn(self) -> None:
        """Submit a player turn and consume the SSE stream to completion."""
        if not self.game_id or not self.auth_token:
            return  # setup failed; skip

        headers = {"Authorization": f"Bearer {self.auth_token}"}
        player_input = secrets.choice(PLAYER_INPUTS)

        t0 = time.monotonic()

        with self.client.post(
            f"{BASE}/games/{self.game_id}/turns",
            json={"input": player_input},
            headers=headers,
            catch_response=True,
            name="POST /turns",
        ) as resp:
            if resp.status_code not in (200, 201, 202):
                resp.failure(f"Turn submit failed: {resp.status_code} {resp.text}")
                return
            resp.success()
            stream_url: str | None = None
            try:
                stream_url = resp.json().get("data", {}).get("stream_url")
            except Exception:
                pass

        if stream_url:
            for _ in _consume_sse(stream_url, self):
                pass  # consume until turn_complete

        elapsed_ms = (time.monotonic() - t0) * 1000
        # Record total turn latency (submit + stream) as a custom event
        self.environment.events.request.fire(
            request_type="TURN",
            name="full_turn_latency",
            response_time=elapsed_ms,
            response_length=0,
            exception=None,
            context={},
        )


# ── Custom pass/fail checks ───────────────────────────────────────────────────


@events.quitting.add_listener
def _on_quit(environment: LocustEnv, **_kwargs: object) -> None:
    """Fail the run if p95 > 2 s or error rate >= 1 % (AC-28.04)."""
    stats = environment.runner.stats if environment.runner else None
    if stats is None:
        return

    total = stats.total
    total_reqs = total.num_requests
    failures = total.num_failures
    error_pct = (failures / total_reqs * 100) if total_reqs else 0.0
    p95 = total.get_response_time_percentile(0.95) or 0.0

    print(
        f"\n[load_test] total={total_reqs} failures={failures} "
        f"error%={error_pct:.2f} p95={p95:.0f}ms"
    )

    if p95 > P95_BUDGET_MS:
        print(f"[load_test] FAIL — p95 {p95:.0f}ms exceeds budget {P95_BUDGET_MS}ms")
        environment.process_exit_code = 1

    if error_pct >= MAX_ERROR_PCT:
        print(f"[load_test] FAIL — error rate {error_pct:.2f}% >= {MAX_ERROR_PCT}%")
        environment.process_exit_code = 1

    if environment.process_exit_code == 0:
        print("[load_test] PASS — all criteria met")
