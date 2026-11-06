"""Generated-task completeness read from the parent workflow's pin."""

from __future__ import annotations

from yoke_contracts.lifecycle_status import workflow_status_metadata_refusal
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.public_item_target import public_item_target


def task_completion_failure(epic_id) -> str | None:
    """Return a diagnosed refusal, never treat an unread check as passing."""
    try:
        response = call_dispatcher(
            function_id="merge.preflight.epic_task_statuses",
            target=public_item_target(epic_id),
            payload={},
        )
        if not response.success:
            detail = response.error.message if response.error else "read refused"
            return compose_refusal(
                f"task_completion_unavailable: {detail}",
                recovery="Restore the epic task-registry read before merging",
            )
        result = response.result or {}
        success = result.get("successful_task_stage_ids")
        if success is None:
            return workflow_status_metadata_refusal()
        unfinished = [
            row for row in result.get("tasks", []) if row["status"] not in success
        ]
        if unfinished:
            detail = ", ".join(
                f"task {row['task_num']} ({row['status']})" for row in unfinished
            )
            return compose_refusal(
                f"task_completion_incomplete: {detail}",
                recovery="Finish these tasks through their pinned implementation handoff before merging",
            )
        return None
    except Exception as exc:
        return compose_refusal(
            f"task_completion_unavailable: {exc}",
            recovery="Restore the task-registry read before merging",
        )
