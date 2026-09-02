"""Handler for workflow-selected creation over the function-call surface.

Wraps :func:`yoke_core.domain.backlog_create_op.execute_create` so the
CLI ``yoke items create`` path and an external/no-checkout HTTPS call share the
one create op (source-actor resolution, project-sequence allocation,
GitHub sync, board rebuild). Running server-side, ``execute_create``
writes to the authoritative Postgres the deployed core is bound to, which
is exactly what an https ``/yoke idea`` needs.

Production creates carry a typed entry surface. The selected immutable
workflow version decides whether that surface may create the item.

A create through a non-web surface also attests that its filer retrieved
the operator execution-instruction blocks for the target workflow and
project first (``execution_instructions_considered``). The web form
renders those blocks in its own UI and promotion carries an already-filed
item forward, so both stay exempt; so do previews and disposable test
databases. This is the one central check — CLI adapters expose the flag
and pass it through, they never set it for the caller.

Target is ``kind="global"`` with the project named in the payload
(``project``); authz classifies ``items.create`` as PROJECT scope and
resolves the target project from that payload field, so a token actor
needs ``items.write`` on the target project.

The registry deliberately makes this one create function session-optional.
Plain-terminal ``yoke dash`` / ``yoke task`` calls bind the verified token
actor over HTTPS; a local call resolves the universe's operating human in
``item_source_actor``. Session-bound callers keep their existing attribution.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ItemCreateRequest(BaseModel):
    """Payload for ``items.create``.

    Mirrors :func:`backlog_create_op.execute_create`'s arguments.
    """

    title: str = Field(..., description="Item title (<=100 chars).")
    workflow: str = Field(
        ...,
        description="Workflow id selected from the active workflow registry.",
    )
    priority: Optional[str] = Field(
        None,
        description="Priority bucket; defaults to the project's configured default.",
    )
    project: Optional[str] = Field(
        None,
        description="Project slug or id; defaults to the caller's checkout project.",
    )
    deployment_flow: Optional[str] = Field(None, description="Deployment flow id.")
    status: Optional[str] = Field(
        None, description="Initial stage; defaults to the workflow's first stage."
    )
    source: Optional[str] = Field(
        None,
        description="Numeric source actor id; defaults to the authenticated/session actor.",
    )
    owner: Optional[str] = Field(
        None, description="Numeric owner actor id; defaults to the source actor."
    )
    entry_surface: Optional[str] = Field(
        None, description="Typed creation surface allowed by the workflow."
    )
    instruction: Optional[str] = Field(
        None, description="Initial executable instruction stored with the item."
    )
    workflow_posture: Dict[str, Any] = Field(
        default_factory=dict,
        description="Definition-bounded verification, gate, and delivery choices.",
    )
    dry_run: bool = Field(False, description="Preview only; no row, no GitHub sync.")
    execution_instructions_considered: bool = Field(
        False,
        description=(
            "The filer retrieved this workflow and project's operator "
            "execution instructions before authoring. Required for every "
            "non-web entry surface."
        ),
    )


class ItemCreateResponse(BaseModel):
    """Successful result envelope.

    ``public_ref`` is the public ``{prefix}-{sequence}`` reference (for
    example, ``YOK-N``) — the canonical handle for the downstream claim /
    body-write / sync steps, since the internal ``item_id`` can diverge
    from the per-project public sequence. Absent on dry-run.
    """

    item_id: int
    public_ref: Optional[str] = None
    dry_run: bool = False
    log: str = ""
    # The attestation this create was accepted under, so the receipt an
    # auditor reads carries the answer rather than the absence of a refusal.
    execution_instructions_considered: bool = False
    # Resolved operator execution-instruction blocks for the created item,
    # so a creator that executes immediately still receives them without a
    # re-fetch (the read surfaces prepend the same blocks above the body).
    # A separate field, mirroring the item reads, so structured-field
    # writes can never round-trip it back into item content. None on
    # dry-run: no row exists to resolve against.
    execution_instructions: Optional[List[Dict[str, Any]]] = None


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def handle_item_create(request: FunctionCallRequest) -> HandlerOutcome:
    """Route a typed create through ``backlog_create_op.execute_create``."""
    try:
        payload = ItemCreateRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("invalid_payload", f"payload invalid: {exc}")

    # Source actor: an explicit payload source wins; otherwise the
    # token-verified actor (https) so the created row's source is the
    # authenticated caller; otherwise None lets execute_create resolve it
    # from the ambient session (local in-process path).
    source = payload.source
    if source is None and request.actor.actor_id is not None:
        source = str(request.actor.actor_id)

    from yoke_core.domain.backlog_create_op import execute_create
    from yoke_core.domain.item_entry_surface import (
        MISSING_ENTRY_SURFACE_MESSAGE,
        enforce_execution_instructions_considered,
    )

    unconsidered = enforce_execution_instructions_considered(
        workflow=payload.workflow,
        project=payload.project,
        entry_surface=payload.entry_surface,
        considered=payload.execution_instructions_considered,
        dry_run=payload.dry_run,
    )
    if unconsidered:
        return _error("execution_instructions_not_considered", unconsidered)

    captured = io.StringIO()
    result: Dict[str, Any] = execute_create(
        title=payload.title,
        workflow=payload.workflow,
        priority=payload.priority,
        project=payload.project,
        deployment_flow=payload.deployment_flow,
        status=payload.status,
        source=source,
        owner=payload.owner,
        session_id=request.actor.session_id,
        dry_run=payload.dry_run,
        entry_surface=payload.entry_surface,
        instruction=payload.instruction,
        workflow_posture=payload.workflow_posture,
        out=captured,
    )

    if not result.get("success"):
        message = str(result.get("error") or "item create failed")
        code = (
            "entry_surface_denied"
            if message == MISSING_ENTRY_SURFACE_MESSAGE or "does not allow" in message
            else "create_failed"
        )
        return _error(code, message)

    execution_instructions: Optional[List[Dict[str, Any]]] = None
    if not result.get("dry_run"):
        from yoke_core.domain.db_helpers import connect
        from yoke_core.domain.workflow_execution_instructions import (
            resolve_for_item,
        )

        with connect() as conn:
            execution_instructions = resolve_for_item(conn, int(result["item_id"]))

    response = ItemCreateResponse(
        item_id=int(result["item_id"]),
        public_ref=result.get("public_ref"),
        dry_run=bool(result.get("dry_run", False)),
        log=captured.getvalue(),
        execution_instructions_considered=(payload.execution_instructions_considered),
        execution_instructions=execution_instructions,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "items.create",
        "handler": handle_item_create,
        "request_model": ItemCreateRequest,
        "response_model": ItemCreateResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.items_create",
        "target_kinds": ["global"],
        "side_effects": ["item_insert", "github_sync", "rebuild_board"],
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": [
            "workflow_entry_surface",
            "execution_instructions_considered",
        ],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
    },
]


__all__ = [
    "handle_item_create",
    "ItemCreateRequest",
    "ItemCreateResponse",
    "REGISTRATIONS",
]
