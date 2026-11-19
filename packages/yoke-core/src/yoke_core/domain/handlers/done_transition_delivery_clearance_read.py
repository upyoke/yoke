"""Resolve one item's delivery clearance for the merge and done close-outs.

Both close-outs ask the same question: does this item's deployment flow (or
its project's delivery default, when the item names none) discharge delivery
without a release wait? Answering it from the client took two org-admin
reads -- every project's defaults and approvers, and whole flow definitions
-- so a project operator without org admin could merge but not close out.

This read answers on the server, scoped to the target item's own project.
The project always comes from the item, never from the payload, and the
response carries only the verdict: no other project's defaults, no
approvers, no flow definition.

``adapter_status='internal'`` -- engine glue, never an agent CLI surface.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

FUNCTION_ID = "done_transition.delivery_clearance"


class DeliveryClearanceRequest(BaseModel):
    #: The item's pinned workflow, used only to pick its project default.
    workflow_id: str = ""
    #: The item's declared flow; empty resolves the project default.
    deploy_flow: str = ""


class DeliveryClearanceResponse(BaseModel):
    merge_only: bool
    resolved_flow: str = ""
    blocked_reason: str = ""


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _item_project_id(conn: Any, item_id: int) -> int | None:
    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import query_one

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = query_one(conn, f"SELECT project_id FROM items WHERE id={p}", (item_id,))
    return None if row is None else int(row["project_id"])


def resolve_clearance(
    conn: Any, *, item_id: int, workflow_id: str, deploy_flow: str
) -> dict[str, Any]:
    """The verdict for one item; raises ``LookupError`` on an unread fact.

    An empty ``deploy_flow`` takes the item's project default for its
    workflow. No flow at all is merge-only: nothing owes a release wait. A
    flow must be registered, and is merge-only only when its own
    ``target_tier`` is null -- never from the flow id's spelling.
    """
    from yoke_core.domain.deployment_flow_validator import list_registered_flow_ids
    from yoke_core.domain.flow import cmd_get
    from yoke_core.domain.workflow_project_defaults import project_delivery_default

    flow = deploy_flow
    if not flow:
        project_id = _item_project_id(conn, item_id)
        if project_id is None:
            raise LookupError(
                "the target item has no project row to resolve its delivery default"
            )
        if workflow_id:
            flow = project_delivery_default(
                conn, project_id=project_id, workflow_id=workflow_id
            )
        if not flow:
            return {"merge_only": True, "resolved_flow": "", "blocked_reason": ""}
    if flow not in list_registered_flow_ids(conn):
        return {
            "merge_only": False,
            "resolved_flow": flow,
            "blocked_reason": (
                f"deployment_flow {flow!r} is not a registered deployment flow."
            ),
        }
    tier = cmd_get(conn, flow, "target_tier")
    return {"merge_only": tier == "", "resolved_flow": flow, "blocked_reason": ""}


def handle_delivery_clearance(request: FunctionCallRequest) -> HandlerOutcome:
    """Answer :func:`resolve_clearance` for the target item."""
    item_id = request.target.item_id
    if item_id is None:
        return _err("target_invalid", f"{FUNCTION_ID} requires target.public_ref")
    try:
        payload = DeliveryClearanceRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _err("payload_invalid", str(exc))
    try:
        with _connect() as conn:
            result = resolve_clearance(
                conn,
                item_id=int(item_id),
                workflow_id=payload.workflow_id,
                deploy_flow=payload.deploy_flow,
            )
    except Exception as exc:  # noqa: BLE001 - surfaced so the close-out aborts
        return _err("delivery_clearance_failed", str(exc))
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "DeliveryClearanceRequest",
    "DeliveryClearanceResponse",
    "FUNCTION_ID",
    "handle_delivery_clearance",
    "resolve_clearance",
]
