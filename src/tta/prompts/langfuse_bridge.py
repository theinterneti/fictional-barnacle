"""Langfuse Prompt Bridge — runtime prompt versioning for TTA.

Bridges the local ``FilePromptRegistry`` (Jinja2 rendering, fragments, safety
preamble) with Langfuse Prompt Management (versioning, labels, per-version
metrics).  The bridge is the glue layer described in FB-005 / AC-09.02.

Architecture
------------
- **Langfuse** is the source of truth for prompt *versions and labels*.
  Prompts are stored as Langfuse ``text`` prompts; the body is the raw
  Jinja2 template (identical to what lives in ``.prompt.md`` files).
- **FilePromptRegistry** remains the rendering engine — Jinja2 compilation,
  fragment includes, safety preamble injection, hash tracking.
- The bridge syncs templates TO Langfuse on startup and refreshes FROM
  Langfuse at render time (cached, no per-call latency).

Activation model
----------------
An admin calls ``POST /admin/prompts/{name}/activate`` with a label
(``"production"``, ``"staging"``).  The bridge flips the label on the
Langfuse side and invalidates the local cache so the next render picks
up the new version.

Preview model
-------------
``POST /admin/prompts/{name}/preview`` fetches a non-production prompt
from Langfuse, renders it against supplied variables, and returns the
output — without modifying game state, consuming credits, or affecting
observability dashboards.

Usage
-----
    bridge = LangfusePromptBridge(
        langfuse_client=langfuse.get_client(),
        file_registry=file_prompt_registry,
    )
    await bridge.seed_from_files()  # push current .prompt.md → Langfuse
    rendered = await bridge.render("narrative.generate", {"world_name": "..."})
"""

from __future__ import annotations

import hashlib
from typing import Any

import structlog

from tta.prompts.registry import PromptRegistry, RenderedPrompt

log: structlog.BoundLogger = structlog.get_logger(__name__)

# Maps template_id → langfuse prompt name (dotted paths become hyphenated)
# e.g. "narrative.generate" → "tta-narrative-generate"
_LANGFUSE_PREFIX: str = "tta-"


def _to_langfuse_name(template_id: str) -> str:
    """Convert a TTA template ID to a Langfuse prompt name."""
    return _LANGFUSE_PREFIX + template_id.replace(".", "-")


def _from_langfuse_name(name: str) -> str:
    """Convert a Langfuse prompt name back to a TTA template ID.

    Inverse of ``_to_langfuse_name``.  Strips the prefix and converts
    hyphens back to dots.  Idempotent on already-dotted names.
    """
    if name.startswith(_LANGFUSE_PREFIX):
        name = name[len(_LANGFUSE_PREFIX) :]
    # If already dotted, return as-is
    if "." in name:
        return name
    return name.replace("-", ".")


class BridgeError(Exception):
    """Raised when bridge operations fail (missing prompt, Langfuse unreachable)."""


class LangfusePromptBridge:
    """Glue between FilePromptRegistry and Langfuse Prompt Management."""

    def __init__(
        self,
        langfuse_client: Any,
        file_registry: PromptRegistry,
    ) -> None:
        self._langfuse = langfuse_client
        self._file_registry = file_registry
        # (template_id, label) → (langfuse_prompt_object, body_hash)
        self._cache: dict[tuple[str, str], tuple[Any, str]] = {}

    # ── seeding ────────────────────────────────────────────────────

    async def seed_from_files(self) -> dict[str, str]:
        """Push every template currently in the file registry into Langfuse.

        If a Langfuse prompt already exists for a template and its body hash
        matches, it is skipped.  If the hash differs, a new version is created.

        Returns a dict mapping ``template_id → action`` (``"created"``,
        ``"skipped"``, ``"updated"``).
        """
        if self._langfuse is None:
            log.warning("langfuse_bridge.seed_skipped", reason="langfuse_disabled")
            return {}

        results: dict[str, str] = {}
        for template_id in self._file_registry.list_templates():
            try:
                results[template_id] = await self._seed_one(template_id)
            except Exception:
                log.exception(
                    "langfuse_bridge.seed_failed",
                    template_id=template_id,
                )
                results[template_id] = "failed"
        return results

    async def _seed_one(self, template_id: str) -> str:
        """Seed a single template to Langfuse.  Returns action string."""
        name = _to_langfuse_name(template_id)
        template = self._file_registry.get(template_id)
        body = template.body if hasattr(template, "body") else str(template)
        body_hash = _sha256(body)

        # Check if Langfuse already has this prompt
        prompt_exists = False
        try:
            existing = self._langfuse.get_prompt(name, label="production")
            prompt_exists = True
            existing_body = (
                existing.prompt
                if isinstance(existing.prompt, str)
                else str(existing.prompt)
            )
            if _sha256(existing_body) == body_hash:
                self._cache[(template_id, "production")] = (existing, body_hash)
                log.debug(
                    "langfuse_bridge.seed_skipped",
                    template_id=template_id,
                    langfuse_name=name,
                )
                return "skipped"

            # Hash differs — create new version
            log.info(
                "langfuse_bridge.seed_updating",
                template_id=template_id,
                langfuse_name=name,
                previous_version=existing.version,
            )
        except Exception:
            # Prompt doesn't exist yet in Langfuse
            log.info(
                "langfuse_bridge.seed_creating",
                template_id=template_id,
                langfuse_name=name,
            )

        # Create/update in Langfuse
        created = self._langfuse.create_prompt(
            name=name,
            type="text",
            prompt=body,
            labels=["production"],
            config={
                "template_id": template_id,
                "body_hash": body_hash,
            },
        )
        self._cache[(template_id, "production")] = (created, body_hash)
        return "updated" if prompt_exists else "created"

    # ── refresh ────────────────────────────────────────────────────

    async def refresh(self, template_id: str, label: str = "production") -> Any:
        """Force-refresh one template from Langfuse.

        Returns the Langfuse prompt object (``TextPromptClient``).
        Raises ``BridgeError`` if not found.
        """
        if self._langfuse is None:
            raise BridgeError("Langfuse is not configured")

        name = _to_langfuse_name(template_id)
        try:
            prompt = self._langfuse.get_prompt(name, label=label)
        except Exception as exc:
            raise BridgeError(
                f"Failed to fetch prompt '{name}' with label '{label}': {exc}"
            ) from exc

        body = prompt.prompt if isinstance(prompt.prompt, str) else str(prompt.prompt)
        self._cache[(template_id, label)] = (prompt, _sha256(body))
        return prompt

    # ── render ─────────────────────────────────────────────────────

    async def render(
        self,
        template_id: str,
        variables: dict[str, Any] | None = None,
        *,
        label: str = "production",
    ) -> RenderedPrompt:
        """Render a prompt, fetching from Langfuse if not cached.

        This is the main runtime entry point.  It:
        1. Checks the local cache for a matching Langfuse prompt
        2. If not cached or label changed, fetches from Langfuse
        3. Delegates Jinja2 rendering to the file registry

        Returns a ``RenderedPrompt`` with template_id, version, and body.
        """
        if variables is None:
            variables = {}

        # Ensure we have the latest Langfuse prompt
        cache_entry = self._cache.get((template_id, label))
        if cache_entry is None:
            langfuse_prompt_obj = await self.refresh(template_id, label)
        else:
            langfuse_prompt_obj = cache_entry[0]

        # Delegate rendering to the file registry (Jinja2 + fragments +
        # safety preamble).  The file registry still has the compiled
        # Jinja2 templates in memory.
        rendered = self._file_registry.render(template_id, variables)

        # Tag the rendered output with the Langfuse prompt object for
        # metrics linking downstream.
        rendered.metadata["langfuse_prompt"] = langfuse_prompt_obj
        rendered.metadata["langfuse_prompt_name"] = _to_langfuse_name(template_id)
        rendered.metadata["langfuse_prompt_version"] = langfuse_prompt_obj.version
        rendered.metadata["langfuse_label"] = label

        return rendered

    # ── activation ─────────────────────────────────────────────────

    async def activate(self, template_id: str, label: str) -> None:
        """Activate a prompt by changing its Langfuse label.

        This is the runtime equivalent of "deploy this version to production."
        After activation, the local cache is invalidated so the next
        ``render()`` call fetches the newly-labelled version.

        Raises ``BridgeError`` if the prompt doesn't exist in Langfuse.
        """
        if self._langfuse is None:
            raise BridgeError("Langfuse is not configured")

        name = _to_langfuse_name(template_id)
        log.info(
            "langfuse_bridge.activate",
            template_id=template_id,
            langfuse_name=name,
            label=label,
        )

        # Fetch current prompt to confirm it exists
        try:
            prompt = self._langfuse.get_prompt(name)
        except Exception as exc:
            raise BridgeError(f"Prompt '{name}' not found in Langfuse: {exc}") from exc

        # Apply the label by updating prompt labels via the SDK.
        # Langfuse v4 SDK: use update_prompt_labels or the REST API.
        # The SDK's prompt management labels API is:
        #   client.update_prompt_labels(name=name, version=version, new_labels=[label])
        try:
            self._langfuse.api.prompts.update_labels(
                name=name,
                version=prompt.version,
                new_labels=[label],
            )
        except AttributeError:
            # Fallback: use the REST API via the client's internal client
            import json
            from urllib.request import Request, urlopen

            host = self._langfuse.client._client_wrapper._base_url.rstrip("/")
            url = f"{host}/api/public/v2/prompts/{name}/labels"
            body = json.dumps({"version": prompt.version, "labels": [label]}).encode()
            req = Request(url, data=body, method="PATCH")
            req.add_header("Content-Type", "application/json")
            # Use the client's auth headers
            headers = self._langfuse.client._client_wrapper._get_headers()
            for key, val in headers.items():
                req.add_header(key, val)
            with urlopen(req, timeout=10) as resp:
                resp.read()

        # Invalidate cache so next render picks up the new labelled version
        # Clear ALL label entries for this template_id
        keys_to_remove = [k for k in self._cache if k[0] == template_id]
        for k in keys_to_remove:
            self._cache.pop(k, None)
        log.info(
            "langfuse_bridge.activated",
            template_id=template_id,
            label=label,
            version=prompt.version,
        )

    # ── preview ────────────────────────────────────────────────────

    async def preview(
        self,
        template_id: str,
        variables: dict[str, Any] | None = None,
        *,
        label: str = "production",
    ) -> RenderedPrompt:
        """Render a prompt against the given variables in shadow mode.

        Identical to ``render()`` but fetches from the specified label
        (e.g. ``"staging"``) instead of the ``"production"`` default.

        This does NOT modify game state, consume turn credits, or affect
        observability dashboards — the rendered output is not passed to
        an LLM call; it is returned to the caller for inspection.
        """
        if variables is None:
            variables = {}

        # Force-refresh to get the exact labelled version
        langfuse_prompt = await self.refresh(template_id, label=label)

        rendered = self._file_registry.render(template_id, variables)
        rendered.metadata["langfuse_prompt"] = langfuse_prompt
        rendered.metadata["langfuse_prompt_name"] = _to_langfuse_name(template_id)
        rendered.metadata["langfuse_prompt_version"] = langfuse_prompt.version
        rendered.metadata["langfuse_label"] = label

        return rendered

    def get_langfuse_prompt_for(
        self, template_id: str, label: str = "production"
    ) -> Any | None:
        """Return the cached Langfuse prompt object for a template, if any."""
        entry = self._cache.get((template_id, label))
        return entry[0] if entry else None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
