"""Admin prompt management routes (§3.8 / FB-005 / AC-09.02).

Extracted from admin.py to keep concerns separated.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from tta.admin.auth import AdminIdentity, require_admin
from tta.api.errors import AppError
from tta.errors import ErrorCategory
from tta.models.admin import ActivatePromptRequest, PreviewPromptRequest
from tta.prompts.langfuse_bridge import _from_langfuse_name

router = APIRouter(tags=["admin"])
log = structlog.get_logger(__name__)


async def _audit(
    request: Request,
    admin: AdminIdentity,
    *,
    action: str,
    target_type: str,
    target_id: str,
    reason: str = "",
) -> None:
    """Create an immutable audit-log entry for admin actions (FR-26.24)."""
    audit_repo = request.app.state.audit_repo
    if audit_repo is not None:
        await audit_repo.create_and_append(
            admin_id=admin.admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
        )


@router.post("/prompts/{name}/activate")
async def activate_prompt(
    name: str,
    body: ActivatePromptRequest,
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Activate a prompt version by changing its Langfuse label (AC-09.02).

    This is the runtime equivalent of "deploy this version to production."
    The next turn that uses this prompt will fetch the newly-labelled version.
    """
    bridge = request.app.state.prompt_bridge
    if bridge is None:
        raise AppError(
            ErrorCategory.INTERNAL_ERROR,
            "PROMPT_BRIDGE_NOT_CONFIGURED",
            "Langfuse prompt bridge is not configured. Set langfuse_host in settings.",
        )

    template_id = _from_langfuse_name(name)
    await bridge.activate(template_id, label=body.label)

    await _audit(
        request,
        admin,
        action="prompt_activate",
        target_type="prompt",
        target_id=name,
        reason=f"label={body.label}",
    )

    log.info(
        "admin_prompt_activated",
        prompt_name=name,
        label=body.label,
        admin=admin.admin_id,
    )
    return JSONResponse(
        content={"status": "activated", "prompt": name, "label": body.label},
    )


@router.post("/prompts/{name}/preview")
async def preview_prompt(
    name: str,
    body: PreviewPromptRequest,
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Preview a prompt against variables in shadow mode (AC-09.09).

    Renders the specified prompt version against the provided variables
    and returns the rendered output.  This does NOT modify game state,
    consume turn credits, or affect observability dashboards.
    """
    bridge = request.app.state.prompt_bridge
    if bridge is None:
        raise AppError(
            ErrorCategory.INTERNAL_ERROR,
            "PROMPT_BRIDGE_NOT_CONFIGURED",
            "Langfuse prompt bridge is not configured. Set langfuse_host in settings.",
        )

    template_id = _from_langfuse_name(name)
    rendered = await bridge.preview(
        template_id,
        variables=body.variables,
        label=body.label,
    )

    await _audit(
        request,
        admin,
        action="prompt_preview",
        target_type="prompt",
        target_id=name,
        reason=f"label={body.label}",
    )

    log.info(
        "admin_prompt_previewed",
        prompt_name=name,
        label=body.label,
        version=rendered.metadata.get("langfuse_prompt_version"),
        admin=admin.admin_id,
    )
    return JSONResponse(
        content={
            "prompt": name,
            "label": body.label,
            "version": rendered.metadata.get("langfuse_prompt_version"),
            "rendered_body": rendered.text,
            "metadata": {
                "template_id": rendered.template_id,
                "fragment_versions": rendered.fragment_versions,
                "prompt_hash": rendered.prompt_hash,
            },
        },
    )
