"""Validate operator repairs against the pinned item workflow."""

from yoke_core.domain.workflow_runtime import WorkflowRuntime


def validate_item_target_status(
    workflow: WorkflowRuntime,
    new_status: str,
) -> str | None:
    """Return a human-readable validation error, or None when valid."""
    if workflow.accepts_stage(new_status):
        return None
    declared = ", ".join(workflow.stage_ids)
    return (
        f"Error: {new_status!r} is not declared by "
        f"{workflow.workflow_id}@{workflow.version}. Stages: {declared} "
        "(plus blocked, stopped, failed, cancelled)."
    )
