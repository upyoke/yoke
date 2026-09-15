"""Claim a project's default delivery flow onto an item, once.

``items.scalar.update`` writes ``deployment_flow`` unconditionally, which is
correct for an explicit operator reassignment -- changing an already-set
item's flow is a legitimate, deliberate reroute. Resolving an *empty*
field onto a project's configured default is a different act: it must not
overwrite a value set moments earlier through that same claim-gated path
(an operator, via the same session, between the guard's read and this
write). Rather than a new CAS flag on the generic write, this reuses the
plain conditional-UPDATE-by-rowcount idiom
``session_launch_registered_session_binding.adopt_attested_session_identity``
already uses for the same kind of claim-once field.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ClaimDefaultDeploymentFlowRequest(BaseModel):
    flow_id: str = Field(..., min_length=1)


class ClaimDefaultDeploymentFlowResponse(BaseModel):
    item_id: int
    deployment_flow: str
    claimed: bool


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False, error=FunctionError(code=code, message=message)
    )


def handle_claim_default_deployment_flow(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "item" or request.target.item_id is None:
        return _error(
            "invalid_payload",
            "items.deployment_flow.claim_default requires target.kind='item'",
        )
    item_id = int(request.target.item_id)
    try:
        payload = ClaimDefaultDeploymentFlowRequest.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - surfaced as a typed refusal
        return _error("invalid_payload", f"payload invalid: {exc}")
    flow_id = payload.flow_id.strip()

    from yoke_core.domain import db_backend, db_helpers
    from yoke_core.domain.deployment_flow_validator import (
        validate_and_lookup_flow_project,
    )

    with db_helpers.connect() as conn:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT p.slug AS project FROM items i JOIN projects p ON p.id=i.project_id "
            f"WHERE i.id={marker}",
            (item_id,),
        ).fetchone()
        if row is None:
            return _error("not_found", f"item {item_id} not found")
        item_project = str(row["project"] if hasattr(row, "keys") else row[0])
        flow_project, err = validate_and_lookup_flow_project(conn, flow_id, item_project)
        if err:
            return _error("validation_error", err)
        if flow_project and flow_project != item_project:
            return _error(
                "validation_error",
                f"deployment flow {flow_id!r} belongs to project "
                f"{flow_project!r}, not {item_project!r}",
            )
        updated = conn.execute(
            f"UPDATE items SET deployment_flow={marker} WHERE id={marker} "
            "AND (deployment_flow IS NULL OR deployment_flow='')",
            (flow_id, item_id),
        )
        claimed = updated.rowcount == 1
        current = conn.execute(
            f"SELECT deployment_flow FROM items WHERE id={marker}", (item_id,)
        ).fetchone()
        conn.commit()
    stored = str((current["deployment_flow"] if hasattr(current, "keys") else current[0]) or "")
    return HandlerOutcome(
        result_payload={"item_id": item_id, "deployment_flow": stored, "claimed": claimed},
        primary_success=True,
    )


REGISTRATIONS: List[dict] = [
    {
        "function_id": "items.deployment_flow.claim_default",
        "handler": handle_claim_default_deployment_flow,
        "request_model": ClaimDefaultDeploymentFlowRequest,
        "response_model": ClaimDefaultDeploymentFlowResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.items_deployment_flow_claim",
        "target_kinds": ["item"],
        "side_effects": [],
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": ["claim_required"],
        "adapter_status": "internal",
        "claim_required_kind": "item",
    },
]

__all__ = [
    "ClaimDefaultDeploymentFlowRequest",
    "ClaimDefaultDeploymentFlowResponse",
    "REGISTRATIONS",
    "handle_claim_default_deployment_flow",
]
