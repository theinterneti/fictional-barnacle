# S64 Phase 3 — Session Preference Plumbing

> **Parent**: plans/generation-serving-profiles.md §11
> **Status**: 📝 Draft → executing
> **Dependencies**: S64 Phases 1-2 complete (PR #215)

## Goal

Thread `generation_profile` from session creation → DB persistence → API responses
→ turn pipeline → LLM client. Players get `balanced` by default; explicit selection
survives resume/restore.

## Steps

### 1. DB migration (014)
- Add `generation_profile TEXT NOT NULL DEFAULT 'balanced'` to `game_sessions`
- Backfill: not needed (DEFAULT handles existing rows)

### 2. Domain model
- `GameSession` — add `generation_profile: str = "balanced"`
- `TurnState` — add `generation_profile: str | None = None`

### 3. API models
- `CreateGameRequest` — add `generation_profile: str | None` with enum validation
- `GameData` — add `generation_profile: str`
- `GameSummary` — add `generation_profile: str`

### 4. API routes
- `create_game` — validate, store in DB, return in response
- `get_game_state` / `list_games` — include profile in response
- `submit_turn` — read profile from row, set on TurnState

### 5. Pipeline threading
- `dispatch_pipeline` — accept `generation_profile` param, set on TurnState
- `generate_stage` / `_generate_narrative` — pass profile to `guarded_llm_call`
- `guarded_llm_call` — accept `generation_profile`/`traffic_class`, forward to `deps.llm.generate()`

### 6. Lifecycle
- resume/restore routes preserve stored profile

### 7. Admin
- `admin_games.py` returns profile

### 8. Tests
- unit: model validation, profile rejection
- unit: migration structure
- integration: create with profile, restore preserves profile

## Files touched
- `migrations/postgres/versions/014_generation_profile.py` (NEW)
- `src/tta/models/game.py` (GameSession, CreateGameRequest, GameData, GameSummary)
- `src/tta/models/turn.py` (TurnState)
- `src/tta/api/routes/games.py` (create, list, get)
- `src/tta/api/routes/games_turns.py` (submit_turn)
- `src/tta/api/routes/games_lifecycle.py` (resume/restore)
- `src/tta/api/routes/admin_games.py` (if exists)
- `src/tta/pipeline/orchestrator.py` (dispatch_pipeline)
- `src/tta/pipeline/llm_guard.py` (guarded_llm_call)
- `src/tta/pipeline/stages/generate.py` (generate_stage, _generate_narrative)
- `src/tta/persistence/postgres_game.py` (all queries)
- `tests/unit/models/test_game_models.py` (new/existing)
- `tests/unit/test_migration_014.py` (NEW)
