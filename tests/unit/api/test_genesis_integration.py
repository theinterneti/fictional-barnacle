"""Tests for genesis wiring and world-change application (Wave 14)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Generator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import structlog

from tta.models.turn import TurnState, TurnStatus
from tta.models.world import TemplateMetadata, WorldChangeType, WorldTemplate
from tta.pipeline.world_changes import translate_world_updates

# ------------------------------------------------------------------
# _translate_world_updates unit tests
# ------------------------------------------------------------------


class TestTranslateWorldUpdates:
    """Unit tests for the LLM-dict → WorldChange translator."""

    def test_maps_location_keyword_to_player_moved(self) -> None:
        raw = [{"entity": "player", "attribute": "location", "new_value": "cave"}]
        changes = translate_world_updates(raw)
        assert len(changes) == 1
        assert changes[0].type == WorldChangeType.PLAYER_MOVED
        assert changes[0].entity_id == "player"
        assert changes[0].payload["new_value"] == "cave"

    def test_maps_mood_keyword_to_npc_disposition(self) -> None:
        raw = [{"entity": "npc_guard", "attribute": "mood", "new_value": "hostile"}]
        changes = translate_world_updates(raw)
        assert changes[0].type == WorldChangeType.NPC_DISPOSITION_CHANGED

    def test_maps_quest_keyword(self) -> None:
        raw = [
            {
                "entity": "quest_1",
                "attribute": "quest_status",
                "new_value": "complete",
            }
        ]
        changes = translate_world_updates(raw)
        assert changes[0].type == WorldChangeType.QUEST_STATUS_CHANGED

    def test_maps_locked_keyword(self) -> None:
        raw = [{"entity": "door_1", "attribute": "locked", "new_value": "true"}]
        changes = translate_world_updates(raw)
        assert changes[0].type == WorldChangeType.CONNECTION_LOCKED

    def test_maps_unlocked_keyword(self) -> None:
        raw = [{"entity": "door_1", "attribute": "unlocked", "new_value": "true"}]
        changes = translate_world_updates(raw)
        assert changes[0].type == WorldChangeType.CONNECTION_UNLOCKED

    def test_maps_taken_keyword_to_item_taken(self) -> None:
        raw = [{"entity": "sword", "attribute": "taken", "new_value": "true"}]
        changes = translate_world_updates(raw)
        assert changes[0].type == WorldChangeType.ITEM_TAKEN

    def test_maps_visibility_keyword(self) -> None:
        raw = [
            {"entity": "secret_door", "attribute": "visibility", "new_value": "shown"}
        ]
        changes = translate_world_updates(raw)
        assert changes[0].type == WorldChangeType.ITEM_VISIBILITY_CHANGED

    def test_maps_relationship_keyword(self) -> None:
        raw = [
            {
                "entity": "npc_ally",
                "attribute": "relationship",
                "new_value": "friendly",
            }
        ]
        changes = translate_world_updates(raw)
        assert changes[0].type == WorldChangeType.RELATIONSHIP_CHANGED

    def test_unknown_attribute_defaults_to_location_state(self) -> None:
        raw = [{"entity": "torch", "attribute": "brightness", "new_value": "dim"}]
        changes = translate_world_updates(raw)
        assert changes[0].type == WorldChangeType.LOCATION_STATE_CHANGED

    def test_skips_empty_entity(self) -> None:
        raw = [{"entity": "", "attribute": "location", "new_value": "cave"}]
        changes = translate_world_updates(raw)
        assert len(changes) == 0

    def test_skips_missing_entity(self) -> None:
        raw = [{"attribute": "location", "new_value": "cave"}]
        changes = translate_world_updates(raw)
        assert len(changes) == 0

    def test_empty_list_returns_empty(self) -> None:
        assert translate_world_updates([]) == []

    def test_multiple_changes_translated(self) -> None:
        raw = [
            {"entity": "player", "attribute": "position", "new_value": "forest"},
            {"entity": "npc_1", "attribute": "disposition", "new_value": "angry"},
            {"entity": "door", "attribute": "state", "new_value": "open"},
        ]
        changes = translate_world_updates(raw)
        assert len(changes) == 3
        assert changes[0].type == WorldChangeType.PLAYER_MOVED
        assert changes[1].type == WorldChangeType.NPC_DISPOSITION_CHANGED
        assert changes[2].type == WorldChangeType.LOCATION_STATE_CHANGED

    def test_payload_includes_all_fields(self) -> None:
        raw = [
            {
                "entity": "e1",
                "attribute": "state",
                "old_value": "closed",
                "new_value": "open",
                "reason": "player pulled lever",
            }
        ]
        changes = translate_world_updates(raw)
        payload = changes[0].payload
        assert payload["attribute"] == "state"
        assert payload["old_value"] == "closed"
        assert payload["new_value"] == "open"
        assert payload["reason"] == "player pulled lever"

    def test_missing_optional_fields_default_to_none(self) -> None:
        raw = [{"entity": "e1", "attribute": "state"}]
        changes = translate_world_updates(raw)
        payload = changes[0].payload
        assert payload["old_value"] is None
        assert payload["new_value"] is None
        assert payload["reason"] == ""

    def test_none_attribute_handled_gracefully(self) -> None:
        """Attribute key with None value should not raise."""
        raw = [{"entity": "e1", "attribute": None, "new_value": "x"}]
        changes = translate_world_updates(raw)
        assert len(changes) == 1
        assert changes[0].payload["attribute"] == ""

    def test_player_moved_payload_has_from_to(self) -> None:
        raw = [
            {
                "entity": "player",
                "attribute": "location",
                "old_value": "town",
                "new_value": "cave",
            }
        ]
        changes = translate_world_updates(raw)
        p = changes[0].payload
        assert p["from_id"] == "town"
        assert p["to_id"] == "cave"

    def test_npc_disposition_payload_has_disposition(self) -> None:
        raw = [{"entity": "guard", "attribute": "mood", "new_value": "hostile"}]
        changes = translate_world_updates(raw)
        assert changes[0].payload["disposition"] == "hostile"

    def test_quest_status_payload_has_new_status(self) -> None:
        raw = [
            {
                "entity": "q1",
                "attribute": "quest_status",
                "new_value": "complete",
            }
        ]
        changes = translate_world_updates(raw)
        assert changes[0].payload["new_status"] == "complete"

    def test_item_visibility_payload_has_hidden_bool(self) -> None:
        raw = [
            {
                "entity": "door",
                "attribute": "visibility",
                "new_value": "true",
            }
        ]
        changes = translate_world_updates(raw)
        assert changes[0].payload["hidden"] is True

    def test_extra_keys_passed_through(self) -> None:
        """LLM may provide extra keys like from_id directly."""
        raw = [
            {
                "entity": "player",
                "attribute": "location",
                "old_value": "a",
                "new_value": "b",
                "from_id": "loc_a",
                "to_id": "loc_b",
            }
        ]
        changes = translate_world_updates(raw)
        p = changes[0].payload
        assert p["from_id"] == "loc_a"
        assert p["to_id"] == "loc_b"


# ------------------------------------------------------------------
# TemplateRegistry.select_by_preferences tests
# ------------------------------------------------------------------


class TestTemplateRegistrySelectByPreferences:
    """Tests for the preference-based template selection."""

    def test_selects_matching_template(self) -> None:
        from tta.world.template_registry import TemplateRegistry

        registry = TemplateRegistry.__new__(TemplateRegistry)
        # Mocks with real metadata lists for _score_preferences
        t1_meta = SimpleNamespace(
            template_key="fantasy",
            compatible_tones=["dark", "gritty"],
            compatible_tech_levels=["medieval"],
            compatible_magic=["high"],
            compatible_scales=["kingdom"],
        )
        t1 = SimpleNamespace(key="fantasy", metadata=t1_meta)

        t2_meta = SimpleNamespace(
            template_key="scifi",
            compatible_tones=["hopeful"],
            compatible_tech_levels=["futuristic"],
            compatible_magic=["none"],
            compatible_scales=["galaxy"],
        )
        t2 = SimpleNamespace(key="scifi", metadata=t2_meta)

        registry._templates = {"fantasy": t1, "scifi": t2}

        result = registry.select_by_preferences(
            {"tone": "dark", "tech_level": "medieval"}
        )
        assert result.key == "fantasy"

    def test_returns_first_template_when_no_preferences(self) -> None:
        from tta.world.template_registry import TemplateRegistry

        registry = TemplateRegistry.__new__(TemplateRegistry)
        t1 = MagicMock()
        t1.key = "default"
        registry._templates = {"default": t1}

        result = registry.select_by_preferences({})
        assert result.key == "default"

    def test_returns_first_when_no_matches(self) -> None:
        from tta.world.template_registry import TemplateRegistry

        registry = TemplateRegistry.__new__(TemplateRegistry)
        t1 = MagicMock()
        t1.key = "default"
        t1.tone = "dark"
        t1.tech_level = "medieval"
        t1.magic_presence = "high"

        registry._templates = {"default": t1}

        result = registry.select_by_preferences({"tone": "xyz_no_match"})
        # Falls back to first template
        assert result.key == "default"


# ------------------------------------------------------------------
# create_game genesis wiring (HTTP-level tests)
# ------------------------------------------------------------------

_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
_PLAYER_ID = uuid4()


def _settings() -> Any:
    from tta.config import Settings

    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
    )


def _make_result(*, scalar: Any = None) -> MagicMock:
    result = MagicMock()
    result.one_or_none.return_value = None
    result.all.return_value = []
    if scalar is not None:
        result.scalar_one.return_value = scalar
    return result


def _genesis_result_mock() -> MagicMock:
    """A mock GenesisResult returned by run_genesis_lite."""

    result = MagicMock()
    result.world_id = "world_123"
    result.player_location_id = "loc_1"
    result.template_key = "fantasy"
    result.narrative_intro = "You awaken in a dark forest..."
    result.genesis_elements = []
    return result


@pytest.fixture()
def _app_for_genesis(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Create a test app with genesis dependencies mocked."""
    from fastapi.testclient import TestClient

    from tta.api.app import create_app
    from tta.api.deps import (
        get_current_player,
        get_pg,
        require_anonymous_game_limit,
        require_consent,
    )
    from tta.models.player import Player

    settings = _settings()
    monkeypatch.setattr("tta.api.routes.games.get_settings", lambda: settings)
    app = create_app(settings=settings)

    # Mock TemplateRegistry on app.state
    mock_registry = MagicMock()
    mock_template = WorldTemplate(
        metadata=TemplateMetadata(template_key="fantasy", display_name="Fantasy World"),
    )
    mock_registry.get.return_value = mock_template
    mock_registry.select_by_preferences.return_value = mock_template
    app.state.template_registry = mock_registry

    # Mock LLM client and world service
    app.state.llm_client = MagicMock()
    app.state.world_service = MagicMock()

    pg_mock = AsyncMock()

    async def _pg():
        yield pg_mock

    player = Player(id=_PLAYER_ID, handle="Tester", created_at=_NOW)
    app.dependency_overrides[get_pg] = _pg
    app.dependency_overrides[get_current_player] = lambda: player
    app.dependency_overrides[require_consent] = lambda: player
    app.dependency_overrides[require_anonymous_game_limit] = lambda: player

    return app, TestClient(app), pg_mock


class TestCreateGameGenesis:
    """Tests for genesis wiring in the create_game route."""

    @patch("tta.genesis.genesis_lite.run_genesis_lite", new_callable=AsyncMock)
    def test_genesis_success_returns_narrative_intro(
        self,
        mock_genesis: AsyncMock,
        _app_for_genesis: tuple,
    ) -> None:
        """When genesis succeeds, response includes narrative_intro."""
        _, client, pg = _app_for_genesis
        mock_genesis.return_value = _genesis_result_mock()
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),  # count active games
                _make_result(),  # INSERT game
                _make_result(),  # UPDATE genesis result
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/games", json={})

        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["narrative_intro"] == "You awaken in a dark forest..."
        assert data["genesis_status"] == "complete"
        assert data["genesis_error_code"] is None
        assert data["genesis_error_message"] is None
        mock_genesis.assert_awaited_once()

    @patch("tta.genesis.genesis_lite.run_genesis_lite", new_callable=AsyncMock)
    def test_genesis_failure_still_creates_game(
        self,
        mock_genesis: AsyncMock,
        _app_for_genesis: tuple,
    ) -> None:
        """When genesis fails, game is still created with null intro."""
        _, client, pg = _app_for_genesis
        mock_genesis.side_effect = RuntimeError("LLM unavailable")
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),  # count active games
                _make_result(),  # INSERT game
                _make_result(),  # UPDATE degraded genesis metadata
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/games", json={})

        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["narrative_intro"] is None
        assert data["genesis_status"] == "degraded"
        assert data["genesis_error_code"] == "GENESIS_FAILED"
        assert data["genesis_error_message"]

    @patch("tta.genesis.genesis_lite.run_genesis_lite", new_callable=AsyncMock)
    def test_genesis_uses_world_id_for_template_lookup(
        self,
        mock_genesis: AsyncMock,
        _app_for_genesis: tuple,
    ) -> None:
        """When world_id is provided, registry.get() is used."""
        app, client, pg = _app_for_genesis
        mock_genesis.return_value = _genesis_result_mock()
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),
                _make_result(),
                _make_result(),
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/games", json={"world_id": "custom_world"})

        assert resp.status_code == 201
        app.state.template_registry.get.assert_called_once_with("custom_world")

    @patch("tta.genesis.genesis_lite.run_genesis_lite", new_callable=AsyncMock)
    def test_genesis_uses_preferences_for_template_selection(
        self,
        mock_genesis: AsyncMock,
        _app_for_genesis: tuple,
    ) -> None:
        """Without world_id, select_by_preferences() is used."""
        app, client, pg = _app_for_genesis
        mock_genesis.return_value = _genesis_result_mock()
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),
                _make_result(),
                _make_result(),
            ]
        )
        pg.commit = AsyncMock()

        prefs = {"tone": "dark", "tech_level": "medieval"}
        resp = client.post("/api/v1/games", json={"preferences": prefs})

        assert resp.status_code == 201
        app.state.template_registry.select_by_preferences.assert_called_once_with(prefs)

    @patch("tta.genesis.genesis_lite.run_genesis_lite", new_callable=AsyncMock)
    def test_genesis_not_implemented_degrades_gracefully(
        self,
        mock_genesis: AsyncMock,
        _app_for_genesis: tuple,
    ) -> None:
        """NotImplementedError from WorldService is caught gracefully."""
        _, client, pg = _app_for_genesis
        mock_genesis.side_effect = NotImplementedError("InMemoryWorldService")
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),
                _make_result(),
                _make_result(),
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/games", json={})

        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["narrative_intro"] is None
        assert data["genesis_status"] == "degraded"
        assert data["genesis_error_code"] == "GENESIS_UNAVAILABLE"

    @patch("tta.genesis.genesis_lite.run_genesis_lite", new_callable=AsyncMock)
    def test_genesis_timeout_degrades_before_latency_abort(
        self,
        mock_genesis: AsyncMock,
        _app_for_genesis: tuple,
    ) -> None:
        """Slow genesis degrades gracefully before middleware returns 503."""
        app, client, pg = _app_for_genesis
        app.state.settings.latency_budget_abort_ms = 200
        app.state.settings.latency_budget_warn_ms = 0

        async def _slow_genesis(*args: Any, **kwargs: Any) -> None:
            del args, kwargs
            await asyncio.sleep(0.35)

        mock_genesis.side_effect = _slow_genesis
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),
                _make_result(),
                _make_result(),
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/games", json={})

        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["narrative_intro"] is None
        assert data["genesis_status"] == "degraded"
        assert data["genesis_error_code"] == "GENESIS_TIMEOUT"

    @patch("tta.genesis.genesis_lite.run_genesis_lite", new_callable=AsyncMock)
    def test_genesis_cancellation_degrades_gracefully(
        self,
        mock_genesis: AsyncMock,
        _app_for_genesis: tuple,
    ) -> None:
        """Cancelled genesis still returns the created game instead of 503."""
        _, client, pg = _app_for_genesis
        mock_genesis.side_effect = asyncio.CancelledError()
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),
                _make_result(),
                _make_result(),
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/games", json={})

        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["narrative_intro"] is None
        assert data["genesis_status"] == "degraded"
        assert data["genesis_error_code"] == "GENESIS_CANCELLED"

    @patch("tta.genesis.genesis_lite.run_genesis_lite", new_callable=AsyncMock)
    def test_genesis_degradation_persists_explicit_metadata(
        self,
        mock_genesis: AsyncMock,
        _app_for_genesis: tuple,
    ) -> None:
        """Degraded genesis persists status/code into the stored world seed."""
        _, client, pg = _app_for_genesis
        mock_genesis.side_effect = RuntimeError("router offline")
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),
                _make_result(),
                _make_result(),
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/games", json={})

        assert resp.status_code == 201
        update_params = pg.execute.await_args_list[-1].args[1]
        persisted_seed = json.loads(update_params["seed"])
        assert persisted_seed["genesis"]["status"] == "degraded"
        assert persisted_seed["genesis"]["error_code"] == "GENESIS_FAILED"


# ------------------------------------------------------------------
# _dispatch_pipeline world changes (isolated unit tests)
# ------------------------------------------------------------------


class TestDispatchPipelineWorldChanges:
    """Tests that _dispatch_pipeline applies world changes correctly."""

    @pytest.fixture(autouse=True)
    def _reset_structlog(self) -> Generator[None, None, None]:
        structlog.reset_defaults()
        from tta.pipeline import orchestrator as orchestrator_module

        if "bind" in orchestrator_module.log.__dict__:
            del orchestrator_module.log.bind
        yield
        structlog.reset_defaults()

    @pytest.mark.asyncio
    @patch("tta.world.changes.apply_changes", new_callable=AsyncMock)
    @patch("tta.pipeline.orchestrator.run_pipeline", new_callable=AsyncMock)
    async def test_dispatch_exception_logs_persistence_outcome(
        self,
        mock_pipeline: AsyncMock,
        mock_apply: AsyncMock,
    ) -> None:
        """Dispatch exceptions log type and failed-turn persist success."""
        from tta.pipeline.orchestrator import dispatch_pipeline

        game_id = uuid4()
        turn_id = uuid4()

        mock_pipeline.side_effect = RuntimeError("boom")
        turn_repo = AsyncMock()
        store = AsyncMock()

        app_state = SimpleNamespace(
            pipeline_deps=SimpleNamespace(
                turn_repo=turn_repo,
                world=AsyncMock(),
                llm=MagicMock(),
                prompt_registry=MagicMock(),
                relationship_service=None,
            ),
            settings=_settings(),
            turn_result_store=store,
        )

        with structlog.testing.capture_logs() as logs:
            await dispatch_pipeline(app_state, game_id, turn_id, 1, "go north", {})

        mock_apply.assert_not_awaited()
        turn_repo.fail_turn.assert_awaited_once_with(turn_id, narrative_output=None)
        dispatch_failed = [
            e for e in logs if e.get("event") == "pipeline_dispatch_failed"
        ]
        persisted = [
            e
            for e in logs
            if e.get("event") == "pipeline_dispatch_exception_persisted_failure"
        ]
        assert dispatch_failed
        assert dispatch_failed[0]["exception_type"] == "RuntimeError"
        assert persisted
        assert persisted[0]["exception_type"] == "RuntimeError"
        assert persisted[0]["failure_persist_succeeded"] is True

    @pytest.mark.asyncio
    @patch("tta.world.changes.apply_changes", new_callable=AsyncMock)
    @patch("tta.pipeline.orchestrator.run_pipeline", new_callable=AsyncMock)
    async def test_dispatch_exception_log_marks_failed_persist_when_fail_turn_raises(
        self,
        mock_pipeline: AsyncMock,
        mock_apply: AsyncMock,
    ) -> None:
        """Persist failure log includes dispatch exception type and outcome."""
        from tta.pipeline.orchestrator import dispatch_pipeline

        game_id = uuid4()
        turn_id = uuid4()

        mock_pipeline.side_effect = RuntimeError("boom")
        turn_repo = AsyncMock()
        turn_repo.fail_turn.side_effect = RuntimeError("db write failed")
        store = AsyncMock()

        app_state = SimpleNamespace(
            pipeline_deps=SimpleNamespace(
                turn_repo=turn_repo,
                world=AsyncMock(),
                llm=MagicMock(),
                prompt_registry=MagicMock(),
                relationship_service=None,
            ),
            settings=_settings(),
            turn_result_store=store,
        )

        with structlog.testing.capture_logs() as logs:
            await dispatch_pipeline(app_state, game_id, turn_id, 1, "go north", {})

        mock_apply.assert_not_awaited()
        turn_repo.update_status.assert_awaited_once_with(turn_id, "failed")
        persist_failed = [e for e in logs if e.get("event") == "turn_persist_failed"]
        assert persist_failed
        assert persist_failed[0]["dispatch_exception_type"] == "RuntimeError"
        assert persist_failed[0]["failure_persist_succeeded"] is False

    @pytest.mark.asyncio
    @patch("tta.world.changes.apply_changes", new_callable=AsyncMock)
    @patch("tta.pipeline.orchestrator.run_pipeline", new_callable=AsyncMock)
    async def test_world_changes_applied_after_successful_turn(
        self,
        mock_pipeline: AsyncMock,
        mock_apply: AsyncMock,
    ) -> None:
        """After a successful turn with world_state_updates, apply_changes is called."""
        from tta.pipeline.orchestrator import dispatch_pipeline

        game_id = uuid4()
        turn_id = uuid4()

        # Pipeline result with world changes
        result_state = TurnState(
            session_id=game_id,
            turn_id=turn_id,
            turn_number=1,
            player_input="go north",
            game_state={},
            status=TurnStatus.complete,
            narrative_output="You walk north into a cave.",
            model_used="test-model",
            world_state_updates=[
                {
                    "entity": "player",
                    "attribute": "location",
                    "new_value": "cave",
                }
            ],
        )
        mock_pipeline.return_value = result_state

        # Mock app_state
        turn_repo = AsyncMock()
        world_svc = AsyncMock()
        store = AsyncMock()

        app_state = SimpleNamespace(
            pipeline_deps=SimpleNamespace(
                turn_repo=turn_repo,
                world=world_svc,
                llm=MagicMock(),
                prompt_registry=MagicMock(),
            ),
            settings=_settings(),
            turn_result_store=store,
        )

        await dispatch_pipeline(app_state, game_id, turn_id, 1, "go north", {})

        mock_apply.assert_awaited_once()
        applied_changes = mock_apply.call_args[0][0]
        assert len(applied_changes) == 1
        assert applied_changes[0].type == WorldChangeType.PLAYER_MOVED

    @pytest.mark.asyncio
    @patch("tta.world.changes.apply_changes", new_callable=AsyncMock)
    @patch("tta.pipeline.orchestrator.run_pipeline", new_callable=AsyncMock)
    async def test_world_changes_failure_does_not_block_turn(
        self,
        mock_pipeline: AsyncMock,
        mock_apply: AsyncMock,
    ) -> None:
        """apply_changes failure doesn't prevent turn result from publishing."""
        from tta.pipeline.orchestrator import dispatch_pipeline

        game_id = uuid4()
        turn_id = uuid4()

        result_state = TurnState(
            session_id=game_id,
            turn_id=turn_id,
            turn_number=1,
            player_input="go north",
            game_state={},
            status=TurnStatus.complete,
            narrative_output="You walk north.",
            model_used="test-model",
            world_state_updates=[
                {"entity": "p", "attribute": "location", "new_value": "x"}
            ],
        )
        mock_pipeline.return_value = result_state
        mock_apply.side_effect = NotImplementedError("no Neo4j")

        turn_repo = AsyncMock()
        store = AsyncMock()

        app_state = SimpleNamespace(
            pipeline_deps=SimpleNamespace(
                turn_repo=turn_repo,
                world=AsyncMock(),
                llm=MagicMock(),
                prompt_registry=MagicMock(),
            ),
            settings=_settings(),
            turn_result_store=store,
        )

        await dispatch_pipeline(app_state, game_id, turn_id, 1, "go north", {})

        # Turn result still published despite world change failure
        store.publish.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("tta.world.changes.apply_changes", new_callable=AsyncMock)
    @patch("tta.pipeline.orchestrator.run_pipeline", new_callable=AsyncMock)
    async def test_no_world_changes_skips_apply(
        self,
        mock_pipeline: AsyncMock,
        mock_apply: AsyncMock,
    ) -> None:
        """When world_state_updates is None, apply_changes is not called."""
        from tta.pipeline.orchestrator import dispatch_pipeline

        game_id = uuid4()
        turn_id = uuid4()

        result_state = TurnState(
            session_id=game_id,
            turn_id=turn_id,
            turn_number=1,
            player_input="look around",
            game_state={},
            status=TurnStatus.complete,
            narrative_output="You see a forest.",
            model_used="test-model",
            world_state_updates=None,
        )
        mock_pipeline.return_value = result_state

        turn_repo = AsyncMock()
        store = AsyncMock()

        app_state = SimpleNamespace(
            pipeline_deps=SimpleNamespace(
                turn_repo=turn_repo,
                world=AsyncMock(),
                llm=MagicMock(),
                prompt_registry=MagicMock(),
            ),
            settings=_settings(),
            turn_result_store=store,
        )

        await dispatch_pipeline(app_state, game_id, turn_id, 1, "look around", {})

        mock_apply.assert_not_awaited()
