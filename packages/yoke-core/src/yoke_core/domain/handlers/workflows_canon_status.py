"""``workflows.canon_status.list`` -- where each workflow stands against canon.

One row per workflow that has a published canon: the selected local version,
the canon state, and whether the next generation arrives by itself. A workflow
authored in this universe has no canon to stand against, so it is not listed.

``pending_only`` narrows the answer to workflows with an update waiting to be
taken -- the set ``workflows.canon_update.apply_all`` would act on, each row
carrying the ``current_version`` that apply's stale-version guard expects.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class WorkflowCanonStatusListRequest(BaseModel):
    pending_only: bool = False


class WorkflowCanonStatusListResponse(BaseModel):
    rows: List[Dict[str, Any]]


def handle_workflows_canon_status_list(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="workflows.canon_status.list requires target.kind='global'",
                jsonpath="$.target.kind",
            ),
        )
    try:
        payload = WorkflowCanonStatusListRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid", message=str(exc), jsonpath="$.payload"
            ),
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.workflow_canon_reporting import PENDING_CANON_STATES
    from yoke_core.domain.workflow_registry import list_current_workflows

    with connect() as conn:
        workflows = list_current_workflows(conn)
    rows: List[Dict[str, Any]] = []
    for workflow in workflows:
        status = workflow.get("canon_status") or {}
        state = status.get("state")
        if state in (None, "not_applicable"):
            continue
        pending = state in PENDING_CANON_STATES
        if payload.pending_only and not pending:
            continue
        rows.append(
            {
                "workflow_id": workflow["id"],
                "name": workflow["name"],
                "current_version": workflow["current_version"],
                "pending": pending,
                **status,
            }
        )
    return HandlerOutcome(result_payload={"rows": rows}, primary_success=True)


__all__ = [
    "WorkflowCanonStatusListRequest",
    "WorkflowCanonStatusListResponse",
    "handle_workflows_canon_status_list",
]
