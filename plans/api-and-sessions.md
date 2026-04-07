# API & Sessions — Component Technical Plan

> **Phase**: SDD Phase 2 — Component Plan
> **Scope**: HTTP API layer, session management, persistence wiring, minimal web client
> **Input specs**: S10 (API & Streaming), S11 (Player Identity & Sessions), S12 (Persistence Strategy)
> **Parent plan**: `plans/system.md` (normative architecture)
> **Wave**: 4 (depends on Waves 2 + 3: pipeline + world/genesis)
> **Status**: 📝 Draft
> **Last Updated**: 2026-04-07

---

## 1. FastAPI Application Structure

### 1.1 — Application Factory

The application is created via a factory function so that tests can build isolated app
instances with injected dependencies.

```python
# src/tta/api/app.py

from contextlib import asynccontextmanager
from fastapi import FastAPI

from tta.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory. Entry point for uvicorn and tests."""
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # --- Startup ---
        app.state.settings = settings
        app.state.pg = await create_postgres_pool(settings.postgres_url)
        app.state.redis = await create_redis_pool(settings.redis_url)
        app.state.neo4j = create_neo4j_driver(
            settings.neo4j_url, settings.neo4j_user, settings.neo4j_password
        )
        yield
        # --- Shutdown ---
        await app.state.pg.dispose()
        await app.state.redis.aclose()
        await app.state.neo4j.close()

    app = FastAPI(
        title="TTA — Therapeutic Text Adventure",
        version="0.1.0",
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
    )

    # Middleware (applied bottom-up; first listed = outermost)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Last-Event-ID"],
        allow_credentials=True,
    )

    # Routes
    app.include_router(health_router,  prefix="/api/v1")       # /api/v1/health, /api/v1/health/ready
    app.include_router(players_router, prefix="/api/v1")       # /api/v1/players
    app.include_router(games_router,   prefix="/api/v1")       # /api/v1/games
    app.include_router(static_router)                          # / → minimal web client

    # Exception handlers
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    return app
```

Uvicorn invocation (Makefile target `make dev`):

```bash
uv run uvicorn tta.api.app:create_app --reload --factory --host 0.0.0.0 --port 8000
```

### 1.2 — Router Organization

| Router file | Prefix | Endpoints | Auth required |
|-------------|--------|-----------|---------------|
| `routes/health.py` | `/api/v1` | `GET /api/v1/health`, `GET /api/v1/health/ready` | No |
| `routes/players.py` | `/api/v1` | Registration, profile, session token | Mixed |
| `routes/games.py` | `/api/v1` | CRUD, turns, streaming, save/resume | Yes |
| `routes/static.py` | `/` | `GET /` → serves `index.html` | No |

Each router file defines its own `APIRouter` and is included by the factory.

### 1.3 — Dependency Injection

FastAPI `Depends()` functions resolve request-scoped resources. Dependencies live in
`src/tta/api/deps.py`.

```python
# src/tta/api/deps.py

from fastapi import Depends, Request, HTTPException

async def get_pg(request: Request) -> AsyncSession:
    """Yields an async SQLAlchemy session from the app-level pool."""
    async with request.app.state.pg() as session:
        yield session

async def get_redis(request: Request) -> Redis:
    """Returns the app-level Redis connection."""
    return request.app.state.redis

async def get_neo4j(request: Request) -> AsyncDriver:
    """Returns the app-level Neo4j driver."""
    return request.app.state.neo4j

async def get_current_player(
    request: Request,
    pg: AsyncSession = Depends(get_pg),
) -> Player:
    """Validate session token and return the authenticated Player.

    Token lookup: cookie first, then Authorization header.
    Raises 401 if missing/invalid/expired.
    """
    token = _extract_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="AUTH_TOKEN_MISSING")

    session_row = await player_sessions_repo.get_by_token(pg, token)
    if session_row is None or session_row.expires_at < utcnow():
        raise HTTPException(status_code=401, detail="AUTH_TOKEN_INVALID")

    player = await players_repo.get_by_id(pg, session_row.player_id)
    if player is None:
        raise HTTPException(status_code=401, detail="AUTH_TOKEN_INVALID")

    return player


def _extract_token(request: Request) -> str | None:
    """Cookie-first, then Authorization: Bearer header."""
    cookie = request.cookies.get("tta_session")
    if cookie:
        return cookie
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None
```

### 1.4 — Middleware Stack

Applied in order (outermost → innermost):

| # | Middleware | Purpose |
|---|-----------|---------|
| 1 | **CORS** | `CORSMiddleware` from Starlette. Configurable origins (FR-10.67–72). |
| 2 | **Request ID** | Custom. Generates a UUID4 `X-Request-Id` header on every response. Attaches to structlog context for distributed tracing (FR-10.54). |
| 3 | **Rate Limiting** | Custom. Per-player rate limiting via Redis counters. Applied after auth resolves a player ID. Returns 429 with `Retry-After` header (FR-10.61–66). |

**Error handlers** are registered separately (not middleware) and produce the standard
error envelope described in §7.

### 1.5 — Lifespan Events

| Event | Action |
|-------|--------|
| **Startup** | Create asyncpg pool. Create Redis pool. Create Neo4j driver. Validate all three connections (log warnings on failure — don't crash). Run Alembic `heads` check (warn if migrations are pending). |
| **Shutdown** | Dispose asyncpg pool. Close Redis pool. Close Neo4j driver. Log shutdown. |

The app starts even if Langfuse is unreachable (system.md §5.3). If Redis is down at
startup, the app starts in degraded mode and logs a warning — `/ready` will report
`cache: "unavailable"`.

---

## 2. Route Specifications

### 2.1 — Player Registration (`POST /api/v1/players`)

v1 auth is **anonymous handles only** (system.md §5.2). No email, no password, no JWT.
A player picks a unique handle and receives a server-side session token.

**Request:**

```python
class CreatePlayerRequest(BaseModel):
    handle: str = Field(
        ..., min_length=1, max_length=50,
        pattern=r"^[a-zA-Z0-9 _\-\.]+$",
        description="Unique player handle. 1–50 chars: letters, numbers, spaces, hyphens, underscores, periods.",
    )
```

**Response (201 Created):**

```python
class CreatePlayerResponse(BaseModel):
    data: PlayerData

class PlayerData(BaseModel):
    player_id: str          # UUID
    handle: str
    created_at: datetime    # ISO 8601 UTC
    session_token: str      # 32-byte hex — also set as cookie
```

**Headers on 201:**

```
Set-Cookie: tta_session=<token>; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=86400
```

**Behavior:**

- Generates a `UUID4` player ID and inserts into `players`.
- Generates a 32-byte random hex token, inserts into `player_sessions` with 24-hour expiry.
- If handle is taken: `409 Conflict`, code `HANDLE_ALREADY_TAKEN`.
- Auth: None required (this is the registration endpoint).
- Rate limit: 5 per hour per IP (since no player ID exists yet).

**Error responses:**

| Status | Code | Condition |
|--------|------|-----------|
| 409 | `HANDLE_ALREADY_TAKEN` | Handle uniqueness violation |
| 422 | `VALIDATION_ERROR` | Handle fails format/length rules |

### 2.2 — Player Profile (`GET /api/v1/players/me`)

**Response (200 OK):**

```python
class PlayerProfileResponse(BaseModel):
    data: PlayerProfile

class PlayerProfile(BaseModel):
    player_id: str
    handle: str
    created_at: datetime
```

Auth: session token required.

### 2.3 — Update Player (`PATCH /api/v1/players/me`)

**Request:**

```python
class UpdatePlayerRequest(BaseModel):
    handle: str | None = Field(
        None, min_length=1, max_length=50,
        pattern=r"^[a-zA-Z0-9 _\-\.]+$",
    )
```

**Response (200 OK):** Same shape as `PlayerProfile`.

Uniqueness check on new handle. Returns 409 if taken.

### 2.4 — Create Game (`POST /api/v1/games`)

**Request:**

```python
class CreateGameRequest(BaseModel):
    world_id: str | None = None         # Defaults to system default world
    preferences: dict[str, str] = {}    # Optional player preferences for this game
```

**Response (201 Created):**

```python
class GameResponse(BaseModel):
    data: GameData

class GameData(BaseModel):
    game_id: str            # UUID
    player_id: str
    world_id: str
    status: str             # "created"
    turn_count: int         # 0
    created_at: datetime
    updated_at: datetime
```

**Behavior:**

- Player must not have more than 5 non-terminal (status in `created`, `active`, `paused`)
  games. If at limit: `409 Conflict`, code `MAX_GAMES_REACHED` (FR-10.10).
- Runs Genesis-lite to populate `world_seed` JSONB.
- Inserts `game_sessions` row with status `created`.
- Creates the Neo4j world graph from the seed.
- Sets initial game state snapshot in Redis.
- Auth: session token required.
- Rate limit: 5 per hour per player.

### 2.5 — List Games (`GET /api/v1/games`)

**Query params:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | string | `null` (all) | Filter by status |
| `cursor` | string | `null` | Cursor for pagination |
| `limit` | int | 20 | Page size (max 50) |

**Response (200 OK):**

```python
class GameListResponse(BaseModel):
    data: list[GameSummary]
    meta: PaginationMeta

class GameSummary(BaseModel):
    game_id: str
    world_id: str
    status: str
    turn_count: int
    created_at: datetime
    updated_at: datetime

class PaginationMeta(BaseModel):
    next_cursor: str | None
    has_more: bool
```

Ordered by `updated_at` DESC (FR-10.12). Only returns games for the authenticated
player (FR-10.14).

### 2.6 — Get Game State (`GET /api/v1/games/{game_id}`)

**Response (200 OK):**

```python
class GameStateResponse(BaseModel):
    data: FullGameState

class FullGameState(BaseModel):
    game_id: str
    player_id: str
    world_id: str
    status: str
    turn_count: int
    created_at: datetime
    updated_at: datetime
    current_location: LocationSummary | None    # Name, description, exits
    recent_turns: list[TurnSummary]             # Last 10 turns
    game_state: dict                            # Current snapshot (inventory, etc.)
    processing_turn: str | None                 # turn_id if in-flight, else null

class LocationSummary(BaseModel):
    location_id: str
    name: str
    description: str
    exits: list[str]

class TurnSummary(BaseModel):
    turn_id: str
    turn_number: int
    player_input: str
    narrative_output: str
    created_at: datetime
```

Returns 404 if game does not exist or is not owned by the player (FR-10.16, FR-11.34).
Response contains enough state for a client to fully render without additional requests
(FR-10.15). The `processing_turn` field is non-null when a turn has status `processing`
(EC-10.05/06).

### 2.7 — Submit Turn (`POST /api/v1/games/{game_id}/turns`)

**Request:**

```python
class TurnRequest(BaseModel):
    input: str = Field(
        ..., min_length=1, max_length=2000,
        description="Player's natural-language input.",
    )
    idempotency_key: str | None = Field(
        None, description="Client-generated UUID. Prevents duplicate submissions."
    )

    @field_validator("input")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Input must not be blank")
        return v
```

**Response (202 Accepted):**

```python
class TurnAcceptedResponse(BaseModel):
    data: TurnAccepted

class TurnAccepted(BaseModel):
    turn_id: str
    turn_number: int
    stream_url: str     # "/api/v1/games/{game_id}/stream"
```

**Behavior:**

1. Validate ownership (404 if not the player's game).
2. Check game status — must be `active` or `created`. Reject `paused`/`ended`/etc. with 422.
3. **Concurrent turn check** (Postgres-based, not Redis):
   ```sql
   SELECT id FROM turns
   WHERE session_id = $1 AND status = 'processing'
   FOR UPDATE;
   ```
   If a row exists → `409 Conflict`, code `TURN_IN_PROGRESS` (FR-10.07).
   The `FOR UPDATE` lock serializes concurrent submissions — a second request blocks
   until the first transaction commits, then sees the in-flight row and returns 409.
4. **Idempotency check**: If `idempotency_key` is provided, check for existing turn with
   same session + key. If found, return existing `turn_id` without reprocessing.
5. Insert turn row (status=`processing`), compute `turn_number` from max + 1.
6. If game was in `created` state, transition to `active`.
7. Dispatch pipeline processing as a background task (`asyncio.create_task`).
8. Return 202 immediately (within 500ms — FR-10.05).

- Rate limit: 10 per minute per player (FR-10.61).
- Empty/whitespace input → 422 (FR-10.08). Over 2000 chars → 422 (FR-10.09).

### 2.8 — Game SSE Stream (`GET /api/v1/games/{game_id}/stream`)

See §3 (SSE Implementation) for full details.

### 2.9 — Save Game (`POST /api/v1/games/{game_id}/save`)

**Response (200 OK):**

```python
class SaveConfirmation(BaseModel):
    data: SaveResult

class SaveResult(BaseModel):
    game_id: str
    saved_at: datetime
    turn_count: int
```

Snapshots current game state from Redis to Postgres. Idempotent — saving an
already-up-to-date game is a no-op that returns the latest snapshot timestamp.

### 2.10 — Resume Game (`POST /api/v1/games/{game_id}/resume`)

**Response (200 OK):** Same shape as `FullGameState` (§2.6).

**Behavior:**

- If game status is `paused` or `expired`: transition to `active`, rebuild Redis cache
  from Postgres + Neo4j, return full game state.
- If game is already `active`: return current state (no-op).
- If game is `ended` or `abandoned`: return 422 `GAME_NOT_RESUMABLE`.

### 2.11 — Update Game Status (`PATCH /api/v1/games/{game_id}`)

**Request:**

```python
class UpdateGameRequest(BaseModel):
    status: Literal["paused"]   # v1: only pause is an explicit transition
```

**Behavior:**

- `active` → `paused` is the only valid explicit transition via this endpoint.
- `paused` → `active` goes through `POST .../resume`.
- `active` → `ended` goes through `DELETE .../`.
- Invalid transitions return 422 `INVALID_STATE_TRANSITION` (FR-11.39).

### 2.12 — End Game (`DELETE /api/v1/games/{game_id}`)

**Response (200 OK):**

```python
class GameEndedResponse(BaseModel):
    data: GameEndedData

class GameEndedData(BaseModel):
    game_id: str
    status: str         # "ended"
    turn_count: int
    ended_at: datetime
```

Soft delete: transitions status to `ended`, clears Redis cache. Game data is retained
(FR-10.19). An ended game rejects new turns (FR-10.20).

### 2.13 — Health Endpoints

**`GET /api/v1/health`** — Liveness. Returns `200 {"status": "ok"}`. No auth, no
dependency checks (FR-10.23/24).

**`GET /api/v1/health/ready`** — Readiness. Pings Postgres, Redis, Neo4j. Returns 200 or 503.

```python
class ReadyResponse(BaseModel):
    status: str                         # "ready" or "degraded"
    checks: dict[str, str]              # {"database": "ok", "cache": "ok", "graph": "ok"}
```

If any check fails → 503 with the failing check identified (FR-10.26).

### 2.14 — Endpoint Summary Table

| Method | Path | Auth | Rate Limit | Status | Description |
|--------|------|------|------------|--------|-------------|
| `POST` | `/api/v1/players` | No | 5/hr/IP | 201 / 409 / 422 | Register (pick handle) |
| `GET` | `/api/v1/players/me` | Yes | 60/min | 200 / 401 | Get profile |
| `PATCH` | `/api/v1/players/me` | Yes | 10/hr | 200 / 409 / 422 | Update handle |
| `POST` | `/api/v1/games` | Yes | 5/hr | 201 / 409 | Create game |
| `GET` | `/api/v1/games` | Yes | 60/min | 200 | List games |
| `GET` | `/api/v1/games/{id}` | Yes | 60/min | 200 / 404 | Get game state |
| `POST` | `/api/v1/games/{id}/turns` | Yes | 10/min | 202 / 409 / 422 | Submit turn |
| `GET` | `/api/v1/games/{id}/stream` | Yes | 3 concurrent | SSE | SSE stream |
| `POST` | `/api/v1/games/{id}/save` | Yes | 10/hr | 200 | Save game |
| `POST` | `/api/v1/games/{id}/resume` | Yes | 10/hr | 200 / 422 | Resume game |
| `PATCH` | `/api/v1/games/{id}` | Yes | 10/hr | 200 / 422 | Pause game |
| `DELETE` | `/api/v1/games/{id}` | Yes | 10/hr | 200 / 404 | End game |
| `GET` | `/api/v1/health` | No | None | 200 | Liveness |
| `GET` | `/api/v1/health/ready` | No | None | 200 / 503 | Readiness |

---

## 3. SSE Implementation

### 3.1 — Architecture: Buffer-Then-Stream

Per system.md §2.4, v1 uses **buffer-then-stream**: the generation stage collects the
full LLM response into a buffer, the post-generation safety hook inspects it, and only
then does delivery stream the tokens to the client via SSE. This means:

- SSE events are NOT produced live from the LLM — they are replayed from a completed buffer
- The buffer lives in Redis as part of the pub/sub event delivery
- Time-to-first-token includes the full LLM generation time (target: < 3s p95)

### 3.2 — Connection Lifecycle

```
Client                                      Server
  │                                           │
  │── GET /api/v1/games/{id}/stream ─────────▶│
  │   Headers: Authorization, Accept           │
  │                                           │── Validate token
  │                                           │── Verify game ownership
  │                                           │── Check: is a completed turn pending replay?
  │                                           │      Yes → send narrative_block event
  │◀──── retry: 3000 ────────────────────────│
  │◀──── event: connected ───────────────────│
  │                                           │── Subscribe to Redis channel
  │                                           │      sse:{session_id}:stream
  │        ... idle ...                       │
  │◀──── event: heartbeat ───────────────────│  (every 15s)
  │        ... idle ...                       │
  │                                           │── [Turn submitted via POST /turns]
  │                                           │── Pipeline runs, buffers response
  │                                           │── Pipeline publishes events to Redis channel
  │◀──── event: turn_start ──────────────────│
  │◀──── event: narrative_token ─────────────│  (repeated)
  │◀──── event: world_update ────────────────│
  │◀──── event: turn_complete ───────────────│
  │        ... idle ...                       │
  │◀──── event: heartbeat ───────────────────│
  │                                           │
  │── (client disconnects) ──────────────────▶│── Unsubscribe Redis channel
  │                                           │── Release connection resources (< 5s)
```

### 3.3 — Route Handler

```python
# src/tta/api/routes/games.py (SSE endpoint)

from fastapi.responses import StreamingResponse

@router.get("/games/{game_id}/stream")
async def game_stream(
    game_id: str,
    request: Request,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
    redis: Redis = Depends(get_redis),
):
    game = await games_repo.get_by_id(pg, game_id)
    if game is None or game.player_id != player.id:
        raise HTTPException(404, "GAME_NOT_FOUND")

    # Check concurrent SSE connection limit (3 per player)
    conn_count = await redis.incr(f"sse:conn:{player.id}")
    await redis.expire(f"sse:conn:{player.id}", 3600)
    if conn_count > 3:
        await redis.decr(f"sse:conn:{player.id}")
        raise HTTPException(429, "SSE_CONNECTION_LIMIT")

    async def event_generator():
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(f"sse:{game_id}:stream")

            # Reconnection: check for completed turn the client may have missed
            latest_turn = await turns_repo.get_latest(pg, game_id)
            if latest_turn and latest_turn.status == "complete":
                yield format_sse("narrative_block", {
                    "turn_id": str(latest_turn.id),
                    "turn_number": latest_turn.turn_number,
                    "narrative": latest_turn.narrative_output,
                })

            # Suggest reconnection delay
            yield f"retry: 3000\n\n"
            yield format_sse("connected", {"game_id": game_id})

            last_heartbeat = time.monotonic()
            while True:
                if await request.is_disconnected():
                    break

                msg = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True),
                    timeout=1.0,
                )

                if msg and msg["type"] == "message":
                    yield msg["data"].decode()
                    last_heartbeat = time.monotonic()

                # Heartbeat every 15 seconds (FR-10.38)
                if time.monotonic() - last_heartbeat >= 15:
                    yield format_sse("heartbeat", {"timestamp": utcnow_iso()})
                    last_heartbeat = time.monotonic()

        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(f"sse:{game_id}:stream")
            await pubsub.aclose()
            await redis.decr(f"sse:conn:{player.id}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
```

### 3.4 — SSE Event Formatting

```python
# src/tta/api/sse.py

import json
from typing import Any

_event_counter = 0  # Per-connection; reset on new connection.

def format_sse(event: str, data: Any, event_id: int | None = None) -> str:
    """Format a single SSE event per RFC 8895."""
    global _event_counter
    if event_id is None:
        _event_counter += 1
        event_id = _event_counter

    payload = json.dumps(data, default=str)
    lines = payload.split("\n")
    data_lines = "\n".join(f"data: {line}" for line in lines)
    return f"id: {event_id}\nevent: {event}\n{data_lines}\n\n"
```

In practice, the event counter is scoped per-connection (not a global). The above
is illustrative. The actual implementation uses a connection-scoped counter object.

### 3.5 — Event Types (normative, from system.md §4.2)

| Event | Data shape | When emitted |
|-------|-----------|--------------|
| `connected` | `{game_id}` | On SSE connection established |
| `turn_start` | `{turn_number, timestamp}` | Pipeline begins processing |
| `narrative_token` | `{token}` | Each chunk of narrative text |
| `world_update` | `{changes: [...]}` | World state changed this turn |
| `turn_complete` | `{turn_number, model_used, latency_ms}` | Turn finished |
| `narrative_block` | `{turn_id, turn_number, narrative}` | Full narrative on reconnect |
| `error` | `{code, message, turn_id?}` | Error during processing |
| `heartbeat` | `{timestamp}` | Keep-alive (every 15s) |

### 3.6 — Publishing Events from the Pipeline

The delivery stage (Wave 2) publishes events to the Redis pub/sub channel. The SSE
handler above subscribes to the same channel and forwards events to the client.

```python
# src/tta/pipeline/delivery.py (called by pipeline orchestrator)

async def deliver_turn(
    redis: Redis,
    session_id: str,
    narrative: str,
    turn_number: int,
    model_used: str,
    latency_ms: int,
    world_changes: list[dict],
):
    channel = f"sse:{session_id}:stream"

    await redis.publish(channel, format_sse("turn_start", {
        "turn_number": turn_number,
        "timestamp": utcnow_iso(),
    }))

    # Simulate token-by-token streaming from the buffered response
    for chunk in chunk_narrative(narrative):
        await redis.publish(channel, format_sse("narrative_token", {
            "token": chunk,
        }))

    if world_changes:
        await redis.publish(channel, format_sse("world_update", {
            "changes": world_changes,
        }))

    await redis.publish(channel, format_sse("turn_complete", {
        "turn_number": turn_number,
        "model_used": model_used,
        "latency_ms": latency_ms,
    }))


def chunk_narrative(text: str, target_size: int = 20) -> list[str]:
    """Split narrative into roughly word-aligned chunks.

    Aims for sentence alignment where possible (FR-10.37),
    falling back to word boundaries.
    """
    # Implementation: split on sentence boundaries first, then by
    # target_size words within sentences.
    ...
```

### 3.7 — Reconnection Handling (v1)

v1 does NOT implement full `Last-Event-ID` replay (system.md §6.4). Instead:

1. Client reconnects to `GET /api/v1/games/{id}/stream`.
2. Server checks the latest turn in Postgres for this session.
3. If status is `complete`: sends a `narrative_block` event with full `narrative_output`,
   then resumes listening for the next turn.
4. If status is `processing`: server subscribes to the Redis pub/sub channel and the
   client picks up from whatever events arrive next.
5. If status is `failed`: sends an `error` event with the failure reason.

This is implemented in the `event_generator()` above (§3.3) — the reconnection check
happens at connection time, before the pub/sub subscription loop.

---

## 4. Session Management (v1 — Anonymous Auth)

### 4.1 — Auth Model

v1 uses **anonymous handle-based authentication** with server-side sessions. This is
intentionally minimal (system.md §5.2):

| Aspect | v1 Implementation |
|--------|-------------------|
| Identity | Unique handle (self-chosen) |
| Credential | None — no password, no email |
| Token format | 32-byte hex string (`secrets.token_hex(32)`) |
| Token storage | `player_sessions` Postgres table (system.md §3.2) |
| Token delivery | `Set-Cookie` (httpOnly, Secure, SameSite=Lax) + JSON response body |
| Token acceptance | Cookie **or** `Authorization: Bearer` header |
| Token lifetime | 24 hours |
| Refresh tokens | Not in v1 |
| JWT | Not in v1 |
| Email/password | Not in v1 |
| OAuth | Not in v1 |

### 4.2 — Registration Flow

```
Client                                     Server
  │                                          │
  │── POST /api/v1/players ────────────────▶│
  │   Body: {"handle": "Zara"}              │
  │                                          │── Validate handle format
  │                                          │── Check handle uniqueness (Postgres)
  │                                          │── INSERT INTO players (id, handle)
  │                                          │── token = secrets.token_hex(32)
  │                                          │── INSERT INTO player_sessions (token, player_id, expires_at)
  │◀──── 201 Created ──────────────────────│
  │   Set-Cookie: tta_session=<token>        │
  │   Body: {data: {player_id, handle, session_token}}
```

### 4.3 — Session Validation

Every authenticated request passes through `get_current_player()` (§1.3) which:

1. Extracts token from cookie or `Authorization` header.
2. Looks up `player_sessions` row by token (primary key lookup — fast).
3. Checks `expires_at >= now()`.
4. Loads the associated `Player` record.
5. Returns the `Player` to the route handler. Raises 401 on any failure.

This is a FastAPI `Depends()` — no explicit middleware. It runs only on endpoints that
declare `player: Player = Depends(get_current_player)`.

### 4.4 — Session Expiry and Cleanup

- Token lifetime: 24 hours from creation.
- Expired tokens are rejected at validation time (no background reaper needed for correctness).
- A scheduled cleanup task (cron or background task) deletes expired rows periodically to
  keep the table small:

```sql
DELETE FROM player_sessions WHERE expires_at < now();
```

Run daily. Not time-critical — expired tokens are rejected on read regardless.

### 4.5 — Token Renewal

When a player makes any authenticated request, the server may extend the session:

- If the token has < 4 hours remaining, issue a new `Set-Cookie` with a fresh 24-hour
  expiry and update `expires_at` in Postgres.
- This is a sliding window, not a refresh token.

### 4.6 — What Is NOT in v1

The following S11 features are explicitly deferred to post-MVP (system.md §5.2):

- Email + password registration (`POST /api/v1/auth/register`)
- Login (`POST /api/v1/auth/login`)
- JWT tokens with access/refresh lifecycle
- Anonymous-to-registered upgrade (`POST /api/v1/auth/upgrade`)
- Account lockout after failed login attempts
- Token deny-lists
- RBAC (admin role) — v1 has no admin endpoints
- GDPR account deletion (no PII is collected in v1)

The `players` table and `player_sessions` table are designed to support adding these
features without schema changes (the columns already exist or can be added as nullable).

---

## 5. Persistence Layer

### 5.1 — SQLModel Table Definitions

The core schema from system.md §3.2 is **normative**. These are the corresponding
SQLModel classes:

```python
# src/tta/models/player.py

from sqlmodel import SQLModel, Field
from datetime import datetime
from uuid import UUID, uuid4


class Player(SQLModel, table=True):
    __tablename__ = "players"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    handle: str = Field(unique=True, index=True, max_length=50)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PlayerSession(SQLModel, table=True):
    __tablename__ = "player_sessions"

    token: str = Field(primary_key=True)            # 32-byte hex
    player_id: UUID = Field(foreign_key="players.id", index=True)
    expires_at: datetime
    created_at: datetime = Field(default_factory=utcnow)
```

```python
# src/tta/models/game.py

class GameSession(SQLModel, table=True):
    __tablename__ = "game_sessions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    player_id: UUID = Field(foreign_key="players.id", index=True)
    status: str = Field(default="created")           # created, active, paused, ended, expired, abandoned
    world_seed: dict = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
```

```python
# src/tta/models/turn.py

class Turn(SQLModel, table=True):
    __tablename__ = "turns"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_number", name="uq_turns_session_turn"),
        UniqueConstraint("session_id", "idempotency_key", name="uq_turns_session_idempotency"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(foreign_key="game_sessions.id", index=True)
    turn_number: int
    idempotency_key: UUID | None = None
    status: str = Field(default="processing")       # processing, complete, failed
    player_input: str
    parsed_intent: dict | None = Field(default=None, sa_column=Column(JSONB))
    world_context: dict | None = Field(default=None, sa_column=Column(JSONB))
    narrative_output: str | None = None
    model_used: str | None = None
    latency_ms: int | None = None
    token_count: dict | None = Field(default=None, sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
```

```python
# src/tta/models/world_event.py

class WorldEvent(SQLModel, table=True):
    __tablename__ = "world_events"
    __table_args__ = (
        Index("ix_world_events_session_created", "session_id", "created_at", postgresql_using="btree"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(foreign_key="game_sessions.id", index=True)
    turn_id: UUID = Field(foreign_key="turns.id")
    event_type: str
    entity_id: str
    payload: dict = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)
```

### 5.2 — Repository Pattern: Async Functions

Repositories are plain async functions grouped by entity module — no classes. This
follows system.md's "keep it simple" ethos. Each function takes an `AsyncSession` as
its first argument for testability (inject a test session in tests).

```python
# src/tta/persistence/players.py

async def create_player(pg: AsyncSession, handle: str) -> Player:
    player = Player(handle=handle)
    pg.add(player)
    await pg.flush()
    return player

async def get_by_id(pg: AsyncSession, player_id: UUID) -> Player | None:
    return await pg.get(Player, player_id)

async def get_by_handle(pg: AsyncSession, handle: str) -> Player | None:
    stmt = select(Player).where(Player.handle == handle)
    result = await pg.execute(stmt)
    return result.scalar_one_or_none()
```

```python
# src/tta/persistence/player_sessions.py

import secrets

async def create_session(
    pg: AsyncSession, player_id: UUID, ttl_hours: int = 24
) -> PlayerSession:
    token = secrets.token_hex(32)
    session = PlayerSession(
        token=token,
        player_id=player_id,
        expires_at=utcnow() + timedelta(hours=ttl_hours),
    )
    pg.add(session)
    await pg.flush()
    return session

async def get_by_token(pg: AsyncSession, token: str) -> PlayerSession | None:
    return await pg.get(PlayerSession, token)

async def delete_expired(pg: AsyncSession) -> int:
    stmt = delete(PlayerSession).where(PlayerSession.expires_at < utcnow())
    result = await pg.execute(stmt)
    return result.rowcount
```

```python
# src/tta/persistence/games.py

async def create_game(
    pg: AsyncSession, player_id: UUID, world_seed: dict
) -> GameSession:
    game = GameSession(player_id=player_id, world_seed=world_seed)
    pg.add(game)
    await pg.flush()
    return game

async def get_by_id(pg: AsyncSession, game_id: UUID) -> GameSession | None:
    return await pg.get(GameSession, game_id)

async def list_for_player(
    pg: AsyncSession,
    player_id: UUID,
    status: str | None = None,
    limit: int = 20,
    cursor: datetime | None = None,
) -> list[GameSession]:
    stmt = (
        select(GameSession)
        .where(GameSession.player_id == player_id)
        .order_by(GameSession.updated_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(GameSession.status == status)
    if cursor:
        stmt = stmt.where(GameSession.updated_at < cursor)
    result = await pg.execute(stmt)
    return list(result.scalars().all())

async def count_active(pg: AsyncSession, player_id: UUID) -> int:
    """Count games in active/paused/created status for game limit check."""
    stmt = (
        select(func.count())
        .select_from(GameSession)
        .where(
            GameSession.player_id == player_id,
            GameSession.status.in_(["active", "paused", "created"]),
        )
    )
    result = await pg.execute(stmt)
    return result.scalar_one()
```

```python
# src/tta/persistence/turns.py

async def create_turn(
    pg: AsyncSession,
    session_id: UUID,
    turn_number: int,
    player_input: str,
    idempotency_key: UUID | None = None,
) -> Turn:
    turn = Turn(
        session_id=session_id,
        turn_number=turn_number,
        player_input=player_input,
        idempotency_key=idempotency_key,
    )
    pg.add(turn)
    await pg.flush()
    return turn

async def get_processing_turn(
    pg: AsyncSession, session_id: UUID
) -> Turn | None:
    """Check for in-flight turn. Uses FOR UPDATE to serialize concurrent submissions."""
    stmt = (
        select(Turn)
        .where(Turn.session_id == session_id, Turn.status == "processing")
        .with_for_update()
    )
    result = await pg.execute(stmt)
    return result.scalar_one_or_none()

async def get_latest(pg: AsyncSession, session_id: UUID) -> Turn | None:
    stmt = (
        select(Turn)
        .where(Turn.session_id == session_id)
        .order_by(Turn.turn_number.desc())
        .limit(1)
    )
    result = await pg.execute(stmt)
    return result.scalar_one_or_none()

async def get_recent(
    pg: AsyncSession, session_id: UUID, limit: int = 10
) -> list[Turn]:
    stmt = (
        select(Turn)
        .where(Turn.session_id == session_id, Turn.status == "complete")
        .order_by(Turn.turn_number.desc())
        .limit(limit)
    )
    result = await pg.execute(stmt)
    return list(reversed(result.scalars().all()))

async def complete_turn(
    pg: AsyncSession,
    turn_id: UUID,
    narrative_output: str,
    parsed_intent: dict | None,
    world_context: dict | None,
    model_used: str,
    latency_ms: int,
    token_count: dict | None,
) -> None:
    stmt = (
        update(Turn)
        .where(Turn.id == turn_id)
        .values(
            status="complete",
            narrative_output=narrative_output,
            parsed_intent=parsed_intent,
            world_context=world_context,
            model_used=model_used,
            latency_ms=latency_ms,
            token_count=token_count,
            completed_at=utcnow(),
        )
    )
    await pg.execute(stmt)
```

### 5.3 — Connection Pool Configuration

```python
# src/tta/persistence/connections.py

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

async def create_postgres_pool(url: str) -> async_sessionmaker:
    engine = create_async_engine(
        url,
        pool_size=20,           # Baseline connections
        max_overflow=10,        # Burst capacity
        pool_timeout=30,        # Seconds to wait for a connection
        pool_recycle=1800,      # Recycle connections every 30 min
        echo=False,             # Set True for SQL debug logging
    )
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_redis_pool(url: str) -> Redis:
    return Redis.from_url(
        url,
        max_connections=50,
        decode_responses=False,  # We handle encoding explicitly
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
    )


def create_neo4j_driver(url: str, user: str, password: str) -> AsyncDriver:
    return AsyncGraphDatabase.driver(
        url,
        auth=(user, password),
        max_connection_pool_size=50,
        connection_acquisition_timeout=30,
    )
```

### 5.4 — Transaction Handling

**Default:** Each route handler gets an `AsyncSession` via `Depends(get_pg)`.
The session auto-commits on successful return from the context manager, auto-rolls-back
on exception.

**Explicit transactions** are used only when multiple writes must be atomic:

```python
# Turn submission: create turn + transition game status
async with pg.begin():
    turn = await turns_repo.create_turn(pg, session_id, turn_number, player_input)
    if game.status == "created":
        game.status = "active"
        game.updated_at = utcnow()
```

**Write-through caching** (FR-12.02): Write to Postgres first, then update Redis.
If the Redis write fails, invalidate the cache key so the next read triggers
reconstruction.

```python
async def save_game_state(
    pg: AsyncSession, redis: Redis, game_id: UUID, state: dict
) -> None:
    # 1. Durable write
    await pg.execute(
        update(GameSession).where(GameSession.id == game_id).values(
            updated_at=utcnow()
        )
    )
    await pg.commit()

    # 2. Cache write (best-effort)
    try:
        await redis.set(
            f"session:{game_id}",
            json.dumps(state),
            ex=3600,  # 1 hour TTL
        )
    except RedisError:
        # Invalidate so next read reconstructs
        await redis.delete(f"session:{game_id}")
```

### 5.5 — Redis Session Cache

**Key pattern** (from system.md §3.4):

```
session:{session_id}          → JSON GameState snapshot (TTL: 1 hour)
sse:{session_id}:stream       → Pub/sub channel for SSE events
```

**Cache operations:**

```python
# src/tta/persistence/redis_session.py

async def get_game_state(redis: Redis, session_id: UUID) -> dict | None:
    """Get cached game state. Returns None on miss."""
    data = await redis.get(f"session:{session_id}")
    if data is None:
        return None
    return json.loads(data)

async def set_game_state(
    redis: Redis, session_id: UUID, state: dict, ttl: int = 3600
) -> None:
    """Set cached game state with TTL."""
    await redis.set(f"session:{session_id}", json.dumps(state), ex=ttl)

async def delete_game_state(redis: Redis, session_id: UUID) -> None:
    """Invalidate cached game state."""
    await redis.delete(f"session:{session_id}")
```

### 5.6 — Cache Miss Handling

When `get_game_state()` returns `None`, the caller must reconstruct the state from
durable stores:

```python
async def get_or_rebuild_game_state(
    pg: AsyncSession, redis: Redis, neo4j: AsyncDriver, session_id: UUID
) -> dict:
    """Load game state from Redis cache, reconstructing from DB on miss."""
    cached = await get_game_state(redis, session_id)
    if cached is not None:
        return cached

    # Cache miss — reconstruct (FR-12.04, target: < 500ms)
    structlog.get_logger().warning("cache_miss_reconstructing", session_id=str(session_id))

    # 1. Load latest turn with game_state_snapshot from Postgres
    game = await games_repo.get_by_id(pg, session_id)
    latest_turn = await turns_repo.get_latest(pg, session_id)

    # 2. Load current world state from Neo4j
    async with neo4j.session() as neo_session:
        location_ctx = await world_service.get_location_context(
            neo_session, str(session_id), game.world_seed.get("start_location")
        )

    # 3. Assemble state
    state = {
        "game_id": str(session_id),
        "status": game.status,
        "turn_count": latest_turn.turn_number if latest_turn else 0,
        "current_location": location_ctx,
        "world_seed": game.world_seed,
    }

    # 4. Re-populate cache
    await set_game_state(redis, session_id, state)

    return state
```

---

## 6. Game Lifecycle

### 6.1 — State Machine

```
  ┌──────────┐
  │  created  │──────────────────────────────────────┐
  └────┬─────┘                                       │
       │ (first turn submitted)                      │
       ▼                                             │
  ┌──────────┐     ┌──────────┐     ┌──────────┐    │
  │  active   │────▶│  paused  │────▶│  active  │    │
  └────┬─────┘     └────┬─────┘     └──────────┘    │
       │                │                            │
       │                │ (timeout: 30 days)         │
       │                ▼                            │
       │           ┌──────────┐                      │
       │           │ expired  │                      │
       │           └──────────┘                      │
       │                                             │
       ▼                                             ▼
  ┌──────────┐                                  ┌──────────┐
  │  ended   │                                  │ abandoned │
  └──────────┘                                  └──────────┘
       (explicit end)                           (no turns + 24h)
```

Valid transitions (FR-11.38):

| From | To | Trigger |
|------|----|---------|
| `created` | `active` | First turn submitted |
| `created` | `abandoned` | No turns within 24 hours (background task) |
| `active` | `paused` | `PATCH /games/{id}` with `status: "paused"` |
| `active` | `ended` | `DELETE /games/{id}` |
| `paused` | `active` | `POST /games/{id}/resume` |
| `paused` | `expired` | 30 days of inactivity (background task) |
| `paused` | `ended` | `DELETE /games/{id}` |
| `expired` | `active` | `POST /games/{id}/resume` |

All other transitions are rejected with `422 INVALID_STATE_TRANSITION`.

### 6.2 — Create Game

1. Validate player is under the 5-game limit.
2. Run Genesis-lite (wave 3): 2-3 LLM prompts → world seed JSON.
3. `INSERT INTO game_sessions` with status `created` and `world_seed` JSONB.
4. Create Neo4j world graph from seed data.
5. Build initial game state dict (start location, empty inventory, etc.).
6. Cache state in Redis (`session:{game_id}`, TTL 1 hour).
7. Return `GameData`.

### 6.3 — Resume Game

1. Validate ownership and status (`paused` or `expired`).
2. Transition status to `active` in Postgres.
3. Rebuild Redis cache from Postgres + Neo4j (same as cache-miss handler, §5.6).
4. Return `FullGameState`.
5. If resuming from `expired`, the next turn's context includes a "welcome back"
   signal for the narrative generator (FR-11.43).

### 6.4 — Save Game

Snapshots the current Redis game state into the `game_sessions.world_seed` or a
supplementary column. In practice, the state is already persisted after every turn
(the `world_context` JSONB on the `turns` table serves as the per-turn snapshot).
An explicit save is a no-op that confirms the latest state is durable — it updates
`game_sessions.updated_at` and returns the timestamp.

### 6.5 — End / Abandon Game

- **End** (explicit, via `DELETE`): Set status to `ended`. Delete Redis cache key.
  Game data is retained in Postgres for history. Neo4j graph data is retained (no
  cleanup in v1 — graph data is small and per-session).
- **Abandon** (background task): Games in `created` status with no turns for > 24 hours
  are transitioned to `abandoned`. After an additional 7 days, abandoned games and their
  graph data may be deleted.

### 6.6 — Background Lifecycle Tasks

A lightweight background task runs on a configurable interval (default: 1 hour) to
handle time-based transitions:

```python
async def lifecycle_cleanup(pg: AsyncSession) -> None:
    """Periodic task for session timeout enforcement."""

    # created → abandoned (24 hours, no turns)
    await pg.execute(
        update(GameSession)
        .where(
            GameSession.status == "created",
            GameSession.created_at < utcnow() - timedelta(hours=24),
        )
        .values(status="abandoned", updated_at=utcnow())
    )

    # paused → expired (30 days)
    await pg.execute(
        update(GameSession)
        .where(
            GameSession.status == "paused",
            GameSession.updated_at < utcnow() - timedelta(days=30),
        )
        .values(status="expired", updated_at=utcnow())
    )

    await pg.commit()
```

This runs as an `asyncio.create_task` in the lifespan startup, sleeping between
iterations. Not time-critical — an hour of drift is acceptable (FR-11.45).

---

## 7. Error Handling

### 7.1 — Error Response Shape (FR-10.51–54)

Every error response uses a consistent envelope:

```json
{
  "error": {
    "code": "TURN_IN_PROGRESS",
    "message": "A turn is already being processed for this game.",
    "details": {},
    "request_id": "a1b2c3d4-..."
  }
}
```

Implementation:

```python
# src/tta/api/errors.py

class AppError(Exception):
    """Application-level error with HTTP status and machine-readable code."""
    def __init__(
        self, status_code: int, code: str, message: str, details: dict | None = None
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}

async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": request.state.request_id,
            }
        },
    )

async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "details": {"errors": exc.errors()},
                "request_id": request.state.request_id,
            }
        },
    )

async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    structlog.get_logger().exception("unhandled_error", request_id=request.state.request_id)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "details": {},
                "request_id": request.state.request_id,
            }
        },
    )
```

### 7.2 — Error Codes

| Code | HTTP | Meaning |
|------|------|---------|
| `AUTH_TOKEN_MISSING` | 401 | No token in cookie or header |
| `AUTH_TOKEN_INVALID` | 401 | Token not found or expired |
| `HANDLE_ALREADY_TAKEN` | 409 | Handle uniqueness violation |
| `GAME_NOT_FOUND` | 404 | Game does not exist or is not owned by player |
| `TURN_IN_PROGRESS` | 409 | Concurrent turn already processing |
| `MAX_GAMES_REACHED` | 409 | Player has 5 active games |
| `GAME_NOT_RESUMABLE` | 422 | Cannot resume ended/abandoned game |
| `INVALID_STATE_TRANSITION` | 422 | Illegal game status change |
| `VALIDATION_ERROR` | 422 | Request body fails Pydantic validation |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests |
| `SSE_CONNECTION_LIMIT` | 429 | 3 concurrent SSE connections exceeded |
| `PAYLOAD_TOO_LARGE` | 413 | Request body > 64KB |
| `SERVICE_UNAVAILABLE` | 503 | Backend dependency down |
| `INTERNAL_ERROR` | 500 | Unhandled exception (no details exposed) |

### 7.3 — 4xx vs 5xx Classification

- **4xx**: Client's fault. Correctable by changing the request. Logged at `warning` level.
- **5xx**: Server's fault. Not correctable by the client. Logged at `error` level with
  full traceback in structured logs. Never exposes stack traces, file paths, or internal
  details to the client (FR-10.56).

### 7.4 — Rate Limit Response Headers

Every authenticated response includes:

```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
X-RateLimit-Reset: 1712520600
```

On 429, additionally:

```
Retry-After: 42
```

Implementation: Redis sliding-window counter keyed on `ratelimit:{player_id}:{endpoint_group}`.

---

## 8. Minimal Web Client

### 8.1 — Purpose

A single HTML file with vanilla JS. Not a product UI — a **test harness** for
evaluating the API, SSE streaming, and gameplay flow (system.md §6.5).

### 8.2 — Capabilities

- Register with a handle
- Create a new game
- Submit turns via text input
- Display narrative token-by-token (SSE `narrative_token` events)
- Display game state (current location, turn count)
- Display connection status (connected, disconnected, reconnecting)
- List existing games and resume them
- No framework, no build step, no dependencies

### 8.3 — Implementation Sketch

```html
<!-- src/tta/static/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>TTA — Therapeutic Text Adventure</title>
  <style>
    body { font-family: monospace; max-width: 800px; margin: 2rem auto; background: #1a1a2e; color: #eee; }
    #narrative { white-space: pre-wrap; min-height: 200px; border: 1px solid #444; padding: 1rem; margin: 1rem 0; }
    #game-state { font-size: 0.85em; color: #aaa; border-top: 1px solid #333; padding-top: 0.5rem; }
    input[type=text] { width: 70%; padding: 0.5rem; font-family: monospace; }
    button { padding: 0.5rem 1rem; cursor: pointer; }
    .status { font-size: 0.8em; }
    .status.connected { color: #4ade80; }
    .status.disconnected { color: #f87171; }
  </style>
</head>
<body>
  <h1>TTA</h1>

  <!-- Registration -->
  <div id="register-section">
    <input type="text" id="handle-input" placeholder="Choose a handle..." />
    <button onclick="register()">Register</button>
  </div>

  <!-- Game controls -->
  <div id="game-section" style="display:none">
    <p>Playing as: <strong id="player-handle"></strong></p>
    <button onclick="createGame()">New Game</button>
    <span class="status" id="connection-status">disconnected</span>

    <div id="narrative"></div>

    <div id="game-state"></div>

    <form onsubmit="submitTurn(event)">
      <input type="text" id="turn-input" placeholder="What do you do?" disabled />
      <button type="submit" id="submit-btn" disabled>Submit</button>
    </form>
  </div>

  <script>
    let sessionToken = null;
    let currentGameId = null;
    let eventSource = null;

    const API = '/api/v1';

    async function apiFetch(path, opts = {}) {
      const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
      if (sessionToken) headers['Authorization'] = `Bearer ${sessionToken}`;
      const res = await fetch(API + path, { ...opts, headers });
      return res;
    }

    async function register() {
      const handle = document.getElementById('handle-input').value.trim();
      if (!handle) return;
      const res = await apiFetch('/players', {
        method: 'POST',
        body: JSON.stringify({ handle }),
      });
      const body = await res.json();
      if (res.ok) {
        sessionToken = body.data.session_token;
        document.getElementById('player-handle').textContent = handle;
        document.getElementById('register-section').style.display = 'none';
        document.getElementById('game-section').style.display = 'block';
      } else {
        alert(body.error?.message || 'Registration failed');
      }
    }

    async function createGame() {
      const res = await apiFetch('/games', { method: 'POST', body: '{}' });
      const body = await res.json();
      if (res.ok) {
        currentGameId = body.data.game_id;
        document.getElementById('turn-input').disabled = false;
        document.getElementById('submit-btn').disabled = false;
        document.getElementById('narrative').textContent = '';
        connectSSE();
      }
    }

    function connectSSE() {
      if (eventSource) eventSource.close();
      const url = `${API}/games/${currentGameId}/stream`;
      eventSource = new EventSource(url);

      const statusEl = document.getElementById('connection-status');
      statusEl.textContent = 'connecting...';
      statusEl.className = 'status';

      eventSource.addEventListener('connected', () => {
        statusEl.textContent = 'connected';
        statusEl.className = 'status connected';
      });

      eventSource.addEventListener('narrative_token', (e) => {
        const { token } = JSON.parse(e.data);
        document.getElementById('narrative').textContent += token;
      });

      eventSource.addEventListener('narrative_block', (e) => {
        const { narrative } = JSON.parse(e.data);
        document.getElementById('narrative').textContent += narrative + '\n\n';
      });

      eventSource.addEventListener('turn_complete', (e) => {
        const data = JSON.parse(e.data);
        document.getElementById('narrative').textContent += '\n\n';
        document.getElementById('turn-input').disabled = false;
        document.getElementById('submit-btn').disabled = false;
      });

      eventSource.addEventListener('world_update', (e) => {
        const { changes } = JSON.parse(e.data);
        document.getElementById('game-state').textContent = JSON.stringify(changes, null, 2);
      });

      eventSource.addEventListener('error', (e) => {
        statusEl.textContent = 'disconnected';
        statusEl.className = 'status disconnected';
      });

      eventSource.onerror = () => {
        statusEl.textContent = 'reconnecting...';
        statusEl.className = 'status disconnected';
      };
    }

    async function submitTurn(e) {
      e.preventDefault();
      const input = document.getElementById('turn-input').value.trim();
      if (!input) return;
      document.getElementById('turn-input').disabled = true;
      document.getElementById('submit-btn').disabled = true;
      document.getElementById('turn-input').value = '';

      const res = await apiFetch(`/games/${currentGameId}/turns`, {
        method: 'POST',
        body: JSON.stringify({ input }),
      });

      if (!res.ok) {
        const body = await res.json();
        alert(body.error?.message || 'Turn submission failed');
        document.getElementById('turn-input').disabled = false;
        document.getElementById('submit-btn').disabled = false;
      }
    }
  </script>
</body>
</html>
```

The web client is served by a static file route:

```python
# src/tta/api/routes/static.py
from fastapi.responses import FileResponse

@router.get("/", include_in_schema=False)
async def index():
    return FileResponse("src/tta/static/index.html")
```

> **Note:** The `EventSource` API does not natively support custom headers. For the
> minimal client, the session token is passed via cookie (`Set-Cookie` on registration).
> External API consumers can use the `Authorization: Bearer` header with a library
> that supports it (e.g., `fetch` with ReadableStream, or a custom EventSource polyfill).

---

## 9. Testing Strategy

### 9.1 — Unit Tests (Route Handlers)

Test each route handler in isolation with mocked dependencies using `httpx.AsyncClient`
and FastAPI's `TestClient` pattern.

```python
# tests/unit/api/test_players.py

import pytest
from httpx import AsyncClient
from tta.api.app import create_app

@pytest.fixture
async def client(mock_pg, mock_redis, mock_neo4j):
    app = create_app(settings=test_settings)
    # Override dependencies
    app.dependency_overrides[get_pg] = lambda: mock_pg
    app.dependency_overrides[get_redis] = lambda: mock_redis
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c

@pytest.mark.asyncio
async def test_register_player_success(client):
    # Arrange
    # (mock_pg configured to allow insert)

    # Act
    response = await client.post("/api/v1/players", json={"handle": "Zara"})

    # Assert
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["handle"] == "Zara"
    assert "session_token" in data
    assert "tta_session" in response.cookies

@pytest.mark.asyncio
async def test_register_duplicate_handle(client):
    response = await client.post("/api/v1/players", json={"handle": "TakenName"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "HANDLE_ALREADY_TAKEN"
```

### 9.2 — Integration Tests

Use `httpx.AsyncClient` against a real FastAPI app with actual Postgres, Redis, and
Neo4j (Docker Compose services, started by `make docker-up`).

```python
# tests/integration/test_game_lifecycle.py

@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_game_lifecycle(integration_client):
    # Register
    res = await integration_client.post("/api/v1/players", json={"handle": "IntegrationTester"})
    assert res.status_code == 201
    token = res.json()["data"]["session_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create game
    res = await integration_client.post("/api/v1/games", json={}, headers=headers)
    assert res.status_code == 201
    game_id = res.json()["data"]["game_id"]

    # Get game state
    res = await integration_client.get(f"/api/v1/games/{game_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "active"

    # Submit turn
    res = await integration_client.post(
        f"/api/v1/games/{game_id}/turns",
        json={"input": "Look around"},
        headers=headers,
    )
    assert res.status_code == 202

    # End game
    res = await integration_client.delete(f"/api/v1/games/{game_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "ended"
```

### 9.3 — SSE Stream Testing

SSE testing requires a client that can read streaming responses. Use `httpx` with
`stream=True` and iterate over the response:

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_sse_stream_receives_turn_events(integration_client, redis):
    # Setup: register, create game, connect SSE
    # ...

    async with integration_client.stream(
        "GET", f"/api/v1/games/{game_id}/stream", headers=headers
    ) as response:
        events = []
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if "turn_complete" in events:
                break

        assert "connected" in events
        assert "narrative_token" in events
        assert "turn_complete" in events
```

### 9.4 — Session Management Tests

```python
@pytest.mark.asyncio
async def test_expired_session_returns_401(client):
    # Arrange: create session with expires_at in the past
    # Act
    response = await client.get("/api/v1/players/me", headers={"Authorization": "Bearer expired-token"})
    # Assert
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_missing_token_returns_401(client):
    response = await client.get("/api/v1/players/me")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_concurrent_turn_returns_409(client):
    # Arrange: insert a turn with status='processing'
    # Act: submit another turn
    # Assert: 409 with TURN_IN_PROGRESS
    ...
```

### 9.5 — BDD Mapping

Key Gherkin scenarios from S10 and S11 are mapped to `pytest-bdd` tests:

| Gherkin scenario | Test file | Status |
|-----------------|-----------|--------|
| Anonymous player starts a game (S11 AC-11.01) | `tests/bdd/step_defs/test_anonymous_play.py` | Wave 4 |
| Turn submission and streaming (S10 AC-10.01) | `tests/bdd/step_defs/test_turn_flow.py` | Wave 4 |
| Game lifecycle transitions (S11 AC-11.04–08) | `tests/bdd/step_defs/test_game_lifecycle.py` | Wave 4 |
| Rate limiting (S10 AC-10.07–08) | `tests/bdd/step_defs/test_rate_limiting.py` | Wave 4 |
| Error response shape (S10 AC-10.09–10) | `tests/bdd/step_defs/test_error_shapes.py` | Wave 4 |
| Player cannot access other's game (S10 AC-10.12) | `tests/bdd/step_defs/test_access_control.py` | Wave 4 |

### 9.6 — Test Markers

```ini
# pyproject.toml [tool.pytest.ini_options]
markers = [
    "unit: Fast isolated tests with mocked dependencies",
    "integration: Tests against real services (Docker Compose)",
    "bdd: Gherkin-driven acceptance tests",
    "sse: Tests involving SSE streaming connections",
]
```

---

## 10. Configuration Summary

All configuration flows through `tta.config.Settings` (system.md §7.4). This section
lists the settings relevant to the API + Sessions component:

| Setting | Env var | Default | Component use |
|---------|---------|---------|---------------|
| `api_host` | `TTA_API_HOST` | `0.0.0.0` | Uvicorn bind address |
| `api_port` | `TTA_API_PORT` | `8000` | Uvicorn port |
| `cors_origins` | `TTA_CORS_ORIGINS` | `["http://localhost:3000"]` | CORS allowed origins |
| `postgres_url` | `TTA_POSTGRES_URL` | `postgresql+asyncpg://tta:tta@localhost:5432/tta` | Asyncpg pool |
| `redis_url` | `TTA_REDIS_URL` | `redis://localhost:6379/0` | Redis pool |
| `neo4j_url` | `TTA_NEO4J_URL` | `bolt://localhost:7687` | Neo4j driver |
| `neo4j_user` | `TTA_NEO4J_USER` | `neo4j` | Neo4j auth |
| `neo4j_password` | `TTA_NEO4J_PASSWORD` | *(required)* | Neo4j auth |
| `max_input_length` | `TTA_MAX_INPUT_LENGTH` | `2000` | Turn input char limit |
| `turn_rate_limit` | `TTA_TURN_RATE_LIMIT` | `10` | Turns per minute per player |
| `session_ttl_seconds` | `TTA_SESSION_TTL_SECONDS` | `86400` | Session token lifetime (24h) |
| `sse_heartbeat_interval` | `TTA_SSE_HEARTBEAT_INTERVAL` | `15` | SSE keepalive interval (seconds) |
| `max_active_games` | `TTA_MAX_ACTIVE_GAMES` | `5` | Per-player game limit |

---

## 11. File Placement

Following the project structure from system.md §2.5:

```
src/tta/
├── api/
│   ├── __init__.py
│   ├── app.py              # Application factory (§1.1)
│   ├── deps.py             # Dependency injection (§1.3)
│   ├── errors.py           # Error types and handlers (§7)
│   ├── middleware.py        # RequestIdMiddleware, rate limiting (§1.4)
│   ├── sse.py              # format_sse(), chunk_narrative() (§3.4)
│   └── routes/
│       ├── __init__.py
│       ├── games.py        # All /games endpoints incl. stream (§2.4–2.12)
│       ├── health.py       # /health, /ready (§2.13)
│       ├── players.py      # /players registration + profile (§2.1–2.3)
│       └── static.py       # / → index.html (§8)
├── models/
│   ├── player.py           # Player, PlayerSession SQLModel (§5.1)
│   ├── game.py             # GameSession SQLModel (§5.1)
│   ├── turn.py             # Turn SQLModel (§5.1)
│   └── world_event.py      # WorldEvent SQLModel (§5.1)
├── persistence/
│   ├── connections.py      # Pool factories (§5.3)
│   ├── players.py          # Player repo functions (§5.2)
│   ├── player_sessions.py  # Session repo functions (§5.2)
│   ├── games.py            # Game repo functions (§5.2)
│   ├── turns.py            # Turn repo functions (§5.2)
│   └── redis_session.py    # Redis cache ops (§5.5)
├── static/
│   └── index.html          # Minimal web client (§8)
└── config.py               # Settings (§10, shared with system.md §7.4)
```
