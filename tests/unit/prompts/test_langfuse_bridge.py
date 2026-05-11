"""Unit tests for LangfusePromptBridge (FB-005)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tta.prompts.langfuse_bridge import (
    BridgeError,
    LangfusePromptBridge,
    _to_langfuse_name,
)

# ── fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def mock_langfuse() -> MagicMock:
    """Return a mock Langfuse client with get_prompt/create_prompt support."""
    lf = MagicMock()
    # get_prompt returns a mock prompt object by default
    mock_prompt = MagicMock()
    mock_prompt.prompt = "You are a helpful assistant."
    mock_prompt.version = 1
    lf.get_prompt.return_value = mock_prompt
    # create_prompt returns a mock
    mock_created = MagicMock()
    mock_created.prompt = "You are a helpful assistant."
    mock_created.version = 1
    lf.create_prompt.return_value = mock_created
    return lf


@pytest.fixture
def mock_registry() -> MagicMock:
    """Return a mock FilePromptRegistry."""
    reg = MagicMock()
    reg.list_templates.return_value = ["narrative.generate", "classification.intent"]
    # get returns a mock template
    template = MagicMock()
    template.body = "You are a game narrator. {{ world_name }}"
    reg.get.return_value = template
    # render returns a mock RenderedPrompt
    rendered = MagicMock()
    rendered.template_id = "narrative.generate"
    rendered.template_version = "1.0.0"
    rendered.text = "You are a game narrator. Haunted Manor"
    rendered.fragment_versions = {}
    rendered.prompt_hash = "abc123"
    rendered.metadata = {}
    reg.render.return_value = rendered
    return reg


@pytest.fixture
def bridge(mock_langfuse, mock_registry) -> LangfusePromptBridge:
    return LangfusePromptBridge(
        langfuse_client=mock_langfuse,
        file_registry=mock_registry,
    )


# ── _to_langfuse_name ─────────────────────────────────────────────


def test_to_langfuse_name_converts_dots_to_hyphens():
    assert _to_langfuse_name("narrative.generate") == "tta-narrative-generate"


def test_to_langfuse_name_single_word():
    assert _to_langfuse_name("health") == "tta-health"


# ── seed_from_files ───────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.spec("AC-09.02")
async def test_seed_creates_new_prompts(bridge, mock_langfuse):
    """New prompts are created in Langfuse when they don't exist."""
    # Simulate: get_prompt raises (prompt doesn't exist)
    mock_langfuse.get_prompt.side_effect = Exception("not found")

    results = await bridge.seed_from_files()

    assert results["narrative.generate"] == "created"
    assert results["classification.intent"] == "created"
    assert mock_langfuse.create_prompt.call_count == 2


@pytest.mark.asyncio
async def test_seed_skips_when_hash_matches(bridge, mock_langfuse):
    """When Langfuse already has a matching hash, skip."""
    mock_langfuse.get_prompt.side_effect = None  # returns successfully
    mock_langfuse.get_prompt.return_value.prompt = (
        "You are a game narrator. {{ world_name }}"
    )

    results = await bridge.seed_from_files()

    assert results["narrative.generate"] == "skipped"
    assert mock_langfuse.create_prompt.call_count == 0


@pytest.mark.asyncio
async def test_seed_returns_empty_when_langfuse_disabled(mock_registry):
    """When Langfuse is None, seed returns empty dict."""
    bridge_no_lf = LangfusePromptBridge(
        langfuse_client=None,
        file_registry=mock_registry,
    )
    results = await bridge_no_lf.seed_from_files()
    assert results == {}


# ── refresh ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_fetches_and_caches(bridge, mock_langfuse):
    """refresh() fetches from Langfuse and stores in cache."""
    mock_langfuse.get_prompt.return_value.prompt = "new body"
    mock_langfuse.get_prompt.return_value.version = 2

    prompt = await bridge.refresh("narrative.generate", label="staging")

    assert prompt.version == 2
    # Cache should now contain the refreshed prompt
    cached = bridge.get_langfuse_prompt_for("narrative.generate")
    assert cached is not None
    assert cached.version == 2


@pytest.mark.asyncio
async def test_refresh_raises_when_langfuse_disabled(mock_registry):
    """refresh() raises BridgeError when Langfuse is not configured."""
    bridge_no_lf = LangfusePromptBridge(
        langfuse_client=None,
        file_registry=mock_registry,
    )
    with pytest.raises(BridgeError, match="not configured"):
        await bridge_no_lf.refresh("narrative.generate")


# ── activate ──────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.spec("AC-09.02")
async def test_activate_changes_label_and_invalidates_cache(bridge, mock_langfuse):
    """activate() flips the label and clears the local cache."""
    # First seed to populate cache
    mock_langfuse.get_prompt.side_effect = None
    mock_langfuse.get_prompt.return_value.prompt = (
        "You are a game narrator. {{ world_name }}"
    )
    mock_langfuse.get_prompt.return_value.version = 1
    await bridge.seed_from_files()

    # Now activate with a different label
    mock_langfuse.api = MagicMock()
    mock_langfuse.api.prompts = MagicMock()
    mock_langfuse.api.prompts.update_labels = MagicMock()

    await bridge.activate("narrative.generate", label="staging")

    # Cache should be invalidated
    assert bridge.get_langfuse_prompt_for("narrative.generate") is None


# ── preview ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.spec("AC-09.09")
async def test_preview_renders_with_label(bridge, mock_registry):
    """preview() fetches from specified label and renders via file registry."""
    rendered = await bridge.preview(
        "narrative.generate",
        variables={"world_name": "Haunted Manor"},
        label="staging",
    )

    assert rendered is not None
    assert "langfuse_prompt" in rendered.metadata
    assert rendered.metadata["langfuse_label"] == "staging"
    assert rendered.metadata["langfuse_prompt_name"] == "tta-narrative-generate"
    mock_registry.render.assert_called_once_with(
        "narrative.generate", {"world_name": "Haunted Manor"}
    )


# ── render ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_delegates_to_file_registry(bridge, mock_registry, mock_langfuse):
    """render() fetches from Langfuse, delegates Jinja2 to file registry."""
    # Pre-seed cache
    mock_langfuse.get_prompt.return_value.prompt = "template body"
    mock_langfuse.get_prompt.return_value.version = 1
    await bridge.seed_from_files()

    rendered = await bridge.render(
        "narrative.generate",
        variables={"world_name": "Haunted Manor"},
    )

    assert rendered is not None
    assert "langfuse_prompt" in rendered.metadata
    assert rendered.metadata["langfuse_label"] == "production"
    mock_registry.render.assert_called_once()


@pytest.mark.asyncio
async def test_render_fetches_when_not_cached(bridge, mock_langfuse, mock_registry):
    """render() fetches from Langfuse when not in cache."""
    # Don't seed — cache is empty
    rendered = await bridge.render("narrative.generate")

    assert rendered is not None
    # Should have fetched from Langfuse
    mock_langfuse.get_prompt.assert_called()


# ── get_langfuse_prompt_for ───────────────────────────────────────


def test_get_langfuse_prompt_for_returns_none_when_not_cached(bridge):
    assert bridge.get_langfuse_prompt_for("nonexistent") is None
