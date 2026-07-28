"""Validate deployment-run membership against current item workflow pins."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_item_binding_validation import (
    WorkflowItemBindingError,
    item_binding_runtime_state,
)
from yoke_core.domain.workflow_runtime import WorkflowRuntime


def _delivery_ready(runtime: WorkflowRuntime, status: str) -> bool:
    position = runtime.stage_index(status)
    if position is None:
        return False
    policy = str(runtime.policies["delivery"])
    if policy == "release_stage":
        starts = [
            runtime.stage_index(str(binding["from_stage_id"]))
            for binding in runtime.definition["executor_bindings"]
            if str(binding["through_stage_id"]) in runtime.terminal_stage_ids
        ]
        valid = [value for value in starts if value is not None]
        return bool(valid) and position >= min(valid)
    if policy == "continuous_slice_actions":
        return runtime.implementation_has_started(status)
    if policy == "after_merge_action":
        return position >= len(runtime.stage_ids) - 2
    return False


def validate_deployment_run_item(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
) -> None:
    """Require project, flow, and delivery-stage compatibility."""
    state = item_binding_runtime_state(conn, int(item_id))
    if state is None:
        return
    runtime, status = state
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    run = conn.execute(
        f"SELECT project_id, flow FROM deployment_runs WHERE id = {marker}",
        (run_id,),
    ).fetchone()
    if run is None:
        raise WorkflowItemBindingError(f"deployment run {run_id!r} not found")
    item = conn.execute(
        f"SELECT project_id, deployment_flow FROM items WHERE id = {marker}",
        (int(item_id),),
    ).fetchone()
    run_project = int(run["project_id"] if hasattr(run, "keys") else run[0])
    run_flow = str(run["flow"] if hasattr(run, "keys") else run[1])
    item_project = int(item["project_id"] if hasattr(item, "keys") else item[0])
    item_flow = item["deployment_flow"] if hasattr(item, "keys") else item[1]
    if item_project != run_project:
        raise WorkflowItemBindingError(
            f"item {item_id} project does not match deployment run {run_id}"
        )
    if item_flow and str(item_flow) != run_flow:
        raise WorkflowItemBindingError(
            f"item {item_id} selects deployment flow {item_flow!r}, not {run_flow!r}"
        )
    if not _delivery_ready(runtime, status):
        raise WorkflowItemBindingError(
            f"item {item_id} workflow {runtime.workflow_id}@{runtime.version} "
            f"is not delivery-ready at stage {status!r}"
        )


def validate_deployment_run_items(
    conn: Any,
    *,
    run_id: str,
    item_ids: Iterable[int],
) -> None:
    for item_id in item_ids:
        validate_deployment_run_item(
            conn,
            run_id=run_id,
            item_id=int(item_id),
        )


__all__ = [
    "validate_deployment_run_item",
    "validate_deployment_run_items",
]
