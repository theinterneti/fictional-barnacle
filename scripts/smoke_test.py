"""Smoke test: Full vertical-slice flow against live API.

1. Health check
2. Register player
3. Create game
4. Submit turn
5. Stream SSE response
"""

import asyncio
import sys

import httpx

BASE = "http://localhost:8000/api/v1"


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as c:
        # ── 1. Health ────────────────────────────────────
        print("1. Health check...")
        r = await c.get(f"{BASE}/health/ready")
        print(f"   {r.status_code} {r.json()}")
        if r.status_code != 200:
            print("   FAIL: readiness probe not healthy")
            sys.exit(1)

        # ── 2. Register player ───────────────────────────
        print("2. Register player...")
        r = await c.post(f"{BASE}/players", json={"handle": "smoke-tester"})
        print(f"   {r.status_code} {r.json()}")
        if r.status_code not in (201, 409):
            print(f"   FAIL: unexpected status {r.status_code}")
            sys.exit(1)

        if r.status_code == 201:
            data = r.json()["data"]
            token = data["session_token"]
            player_id = data["player_id"]
        else:
            # Handle already exists — try a unique name
            import secrets

            handle = f"smoke-{secrets.token_hex(4)}"
            r = await c.post(f"{BASE}/players", json={"handle": handle})
            print(f"   retry: {r.status_code}")
            data = r.json()["data"]
            token = data["session_token"]
            player_id = data["player_id"]

        headers = {"Authorization": f"Bearer {token}"}
        print(f"   Player: {player_id}")
        print(f"   Token:  {token[:16]}...")

        # ── 3. Create game ───────────────────────────────
        print("3. Create game...")
        r = await c.post(
            f"{BASE}/games",
            json={"preferences": {"theme": "fantasy"}},
            headers=headers,
        )
        print(f"   {r.status_code} {r.json()}")
        if r.status_code != 201:
            print(f"   FAIL: unexpected status {r.status_code}")
            sys.exit(1)

        game_id = r.json()["data"]["game_id"]
        print(f"   Game:   {game_id}")

        # ── 4. Submit turn ───────────────────────────────
        print("4. Submit turn: 'look around the tavern'...")
        r = await c.post(
            f"{BASE}/games/{game_id}/turns",
            json={"input": "look around the tavern"},
            headers=headers,
        )
        print(f"   {r.status_code} {r.json()}")
        if r.status_code != 202:
            print(f"   FAIL: unexpected status {r.status_code}")
            sys.exit(1)

        turn_data = r.json()["data"]
        stream_url = turn_data["stream_url"]
        print(f"   Turn #{turn_data['turn_number']} accepted")
        print(f"   Stream: {stream_url}")

        # ── 5. Stream SSE ────────────────────────────────
        print("5. Streaming SSE events...")
        full_url = f"http://localhost:8000{stream_url}"
        events = []

        async with c.stream("GET", full_url, headers=headers) as resp:
            print(f"   SSE status: {resp.status_code}")
            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    if block.strip():
                        events.append(block)
                        # Parse event type
                        lines = block.strip().split("\n")
                        event_type = "message"
                        data_lines = []
                        for line in lines:
                            if line.startswith("event:"):
                                event_type = line[6:].strip()
                            elif line.startswith("data:"):
                                data_lines.append(line[5:].strip())
                        data_str = "\n".join(data_lines)
                        print(f"   [{event_type}] {data_str[:200]}")

        print(f"\n   Total SSE events: {len(events)}")

        # ── Summary ──────────────────────────────────────
        event_types = []
        for e in events:
            for line in e.strip().split("\n"):
                if line.startswith("event:"):
                    event_types.append(line[6:].strip())

        passed = "narrative_block" in event_types
        verdict = "PASSED" if passed else "FAILED"
        print(f"\n=== SMOKE TEST {verdict} ===")
        print(f"Events received: {event_types}")

        if "narrative_block" not in event_types:
            print("ERROR: No narrative_block event received!")
            sys.exit(1)

        if "turn_complete" not in event_types:
            print("ERROR: No turn_complete event received!")
            sys.exit(1)

        print("The vertical slice is functional!")


if __name__ == "__main__":
    asyncio.run(main())
