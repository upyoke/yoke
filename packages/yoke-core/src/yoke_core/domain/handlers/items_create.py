"""Handler for the ``items.create`` function id — sanctioned idea-intake
item creation over the function-call surface (in-process AND https).

Wraps :func:`yoke_core.domain.backlog_create_op.execute_create` so the
CLI ``yoke items create`` path and a Buzz / no-checkout https call share the
one create op (source-actor resolution, project-sequence allocation,
GitHub sync, board rebuild). Running server-side, ``execute_create``
writes to the authoritative Postgres the deployed core is bound to, which
is exactly what an https ``/yoke idea`` needs.

The :mod:`yoke_core.domain.ticket_intake_provenance` gate still applies:
production creates must carry ``provenance="idea"`` in the payload — the
function-call equivalent of the ``YOKE_IDEA_INTAKE`` env var the local
``db_router`` path uses. A create without it fails closed with the
recovery hint that names ``/yoke idea``; this surface is a wrapped
intake path, not a hole around the "``/yoke idea`` is the only entry"
contract.

Target is ``kind="global"`` with the project named in the payload
(``project``); authz classifies ``items.create`` as PROJECT scope and
resolves the target project from that payload field, so a token actor
needs ``items.write`` on the target project.
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

    Mirrors :func:`backlog_create_op.execute_create`'s arguments. ``type``
    matches the JSON field used by the REST create route; the handler maps
    it to the create op's ``item_type`` argument.
    """

    title: str = Field(..., description="Item title (<=100 chars).")
    type: str = Field(..., description="Item type: issue | epic.")
    priority: Optional[str] = Field(
        None, description="Priority bucket; defaults to the project's configured default."
    )
    project: Optional[str] = Field(
        None, description="Project slug or id; defaults to the caller's checkout project."
    )
    deployment_flow: Optional[str] = Field(None, description="Deployment flow id.")
    status: str = Field("idea", description="Initial status (idea intake is always 'idea').")
    source: Optional[str] = Field(
        None, description="Numeric source actor id; defaults to the authenticated/session actor."
    )
    owner: Optional[str] = Field(
        None, description="Numeric owner actor id; defaults to the source actor."
    )
    provenance: Optional[str] = Field(
        None, description="Sanctioned-intake signal; '/yoke idea' sets 'idea'."
    )
    dry_run: bool = Field(False, description="Preview only; no row, no GitHub sync.")


class ItemCreateResponse(BaseModel):
    """Successful result envelope.

    ``item_ref`` is the public ``{prefix}-{sequence}`` reference (for
    example, ``YOK-N``) — the canonical handle for the downstream claim /
    body-write / sync steps, since the internal ``item_id`` can diverge
    from the per-project public sequence. Absent on dry-run.
    """

    item_id: int
    item_ref: Optional[str] = None
    dry_run: bool = False
    log: str = ""


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
    from yoke_core.domain.ticket_intake_provenance import BYPASS_MESSAGE

    captured = io.StringIO()
    result: Dict[str, Any] = execute_create(
        title=payload.title,
        item_type=payload.type,
        priority=payload.priority,
        project=payload.project,
        deployment_flow=payload.deployment_flow,
        status=payload.status,
        source=source,
        owner=payload.owner,
        session_id=request.actor.session_id,
        dry_run=payload.dry_run,
        provenance=payload.provenance,
        out=captured,
    )

    if not result.get("success"):
        message = str(result.get("error") or "item create failed")
        code = "intake_denied" if message == BYPASS_MESSAGE else "create_failed"
        return _error(code, message)

    response = ItemCreateResponse(
        item_id=int(result["item_id"]),
        item_ref=result.get("item_ref"),
        dry_run=bool(result.get("dry_run", False)),
        log=captured.getvalue(),
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
        "guardrails": ["idea_intake_provenance"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "handle_item_create",
    "ItemCreateRequest",
    "ItemCreateResponse",
    "REGISTRATIONS",
]
