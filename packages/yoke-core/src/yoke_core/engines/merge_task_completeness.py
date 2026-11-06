"""Generated-task completeness read from the parent workflow's pin."""

from __future__ import annotations
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.public_item_target import public_item_target


def task_completion_failure(epic_id) -> str | None:
    """Return a diagnosed refusal, never treat an unread check as passing."""
    recovery = "Use the installed CLI matching the serving engine until that engine is upgraded to the next-release serving floor."
    try:
        response = call_dispatcher(
            function_id="merge.preflight.epic_task_statuses",
            target=public_item_target(epic_id),
            payload={},
        )
        if not response.success:
            detail = response.error.message if response.error else "read refused"
            return f"task_completion_unavailable: {detail}; read the epic's task registry before merging."
        result = response.result or {}
        success = result.get("successful_task_stage_ids")
        if success is None:
            return f"workflow_status_metadata_unavailable: {recovery}"
        unfinished = [
            row for row in result.get("tasks", []) if row["status"] not in success
        ]
        if unfinished:
            detail = ", ".join(
                f"task {row['task_num']} ({row['status']})" for row in unfinished
            )
            return f"task_completion_incomplete: {detail}; finish these tasks through their pinned implementation handoff before merging."
        return None
    except Exception as exc:
        return f"task_completion_unavailable: {exc}; restore the task-registry read before merging."
