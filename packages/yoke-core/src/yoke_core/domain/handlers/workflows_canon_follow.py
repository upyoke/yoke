"""``workflows.canon_follow.set`` -- do new generations arrive by themselves.

Following is on by default, and the two ways a universe diverges from the
published canon turn it off: publishing a local edit, and selecting a version
that is not the newest generation. From either state taking an update is a
merge against local work rather than a move onto stock, and nothing decides
that unattended. This is the operator's way back, and the only path that turns
following on -- no other write does it as a side effect.

Turning it on adopts nothing by itself. Applying a definition remains the boot
convergence's job, so a workflow switched back to following takes the update it
is behind on the next boot, or through ``workflows.canon_update.apply`` now.
Both facts are served together by the workflow read, so a page can say which
one the operator is looking at.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class WorkflowCanonFollowSetRequest(BaseModel):
    workflow_id: str
    follow: Literal["auto", "manual"]


class WorkflowCanonFollowSetResponse(BaseModel):
    workflow_id: str
    follow: str


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _canon_state(conn, workflow_id: str) -> Optional[str]:
    """This workflow's canon state, or ``None`` when it has no row.

    Read through the same registry surface the workflows page reads, so
    "has a canon at all" is answered once, in one place, rather than
    reconstructed here from source and generation count.
    """
    from yoke_core.domain.workflow_registry import list_current_workflows

    for row in list_current_workflows(conn):
        if row["id"] == workflow_id:
            return str((row.get("canon_status") or {}).get("state") or "")
    return None


def handle_workflows_canon_follow_set(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "workflows.canon_follow.set requires target.kind='global'",
            "$.target.kind",
        )
    try:
        payload = WorkflowCanonFollowSetRequest.model_validate(
            request.payload or {}
        )
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.workflow_registry_sql import marker

    with connect() as conn:
        state = _canon_state(conn, payload.workflow_id)
        if state is None:
            return _error(
                "not_found",
                f"unknown workflow {payload.workflow_id!r}",
                "$.payload.workflow_id",
            )
        if state == "not_applicable":
            # A following setting for a workflow nothing publishes describes
            # nothing, so storing one would invent a relationship.
            return _error(
                "incompatible",
                f"workflow {payload.workflow_id!r} has no published canon "
                "to follow",
                "$.payload.workflow_id",
            )
        bind = marker(conn)
        conn.execute(
            f"UPDATE workflows SET canon_follow = {bind}, "
            f"updated_at = {bind} WHERE id = {bind}",
            (payload.follow, iso8601_now(), payload.workflow_id),
        )
        conn.commit()
    return HandlerOutcome(
        result_payload={
            "workflow_id": payload.workflow_id,
            "follow": payload.follow,
        },
        primary_success=True,
    )


__all__ = [
    "WorkflowCanonFollowSetRequest",
    "WorkflowCanonFollowSetResponse",
    "handle_workflows_canon_follow_set",
]
