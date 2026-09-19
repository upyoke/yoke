"""Validate deployment-run membership against current item workflow pins."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_project_sources import carried_project_ids
from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_DELIVERY_CONTINUOUS_SLICE_THEN_RELEASE,
)
from yoke_core.domain.workflow_item_binding_validation import (
    WorkflowItemBindingError,
    item_binding_runtime_state,
)
from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    load_item_workflow_runtime,
)
from yoke_core.domain.project_identity import render_item_ref


COMPLETED_ITEM_STAGE_ID = "done"


def delivery_ready_for_stage(runtime: WorkflowRuntime, status: str) -> bool:
    position = runtime.stage_index(status)
    if position is None:
        return False
    policy = str(runtime.policies["delivery"])
    if policy == "release_stage":
        starts = [
            runtime.stage_index(str(binding["from_stage_id"]))
            for binding in runtime.definition["skill_bindings"]
            if str(binding["through_stage_id"]) in runtime.terminal_stage_ids
        ]
        valid = [value for value in starts if value is not None]
        return bool(valid) and position >= min(valid)
    if policy in ("continuous_slice_actions", WORKFLOW_DELIVERY_CONTINUOUS_SLICE_THEN_RELEASE):
        return runtime.implementation_has_started(status)
    if policy == "after_merge_action":
        return position >= len(runtime.stage_ids) - 2
    return False


def _validate_deployment_run_item_state(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    state: tuple[WorkflowRuntime, str] | None,
    allow_completed: bool,
) -> None:
    if state is None:
        return
    runtime, status = state
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    item = conn.execute(
        f"SELECT project_id FROM items WHERE id = {marker}",
        (int(item_id),),
    ).fetchone()
    item_project = int(item["project_id"] if hasattr(item, "keys") else item[0])
    # Membership follows the code, not the run's own project row: a run that
    # binds another project's source ships that project's merges too, and the
    # items inside them are delivered by this run or by nothing.
    try:
        carried = carried_project_ids(conn, run_id)
    except LookupError as exc:
        raise WorkflowItemBindingError(
            f"deployment run {run_id!r} not found"
        ) from exc
    if item_project not in carried:
        raise WorkflowItemBindingError(
            f"{render_item_ref(conn, item_id)} belongs to a project deployment "
            f"run {run_id} ships no source for; the run records a source commit "
            "only for its own project and the projects its flow stages bind "
            "through input_bindings"
        )
    if allow_completed and status == COMPLETED_ITEM_STAGE_ID:
        return
    if not delivery_ready_for_stage(runtime, status):
        raise WorkflowItemBindingError(
            f"{render_item_ref(conn, item_id)} workflow {runtime.workflow_id}@{runtime.version} "
            f"is not delivery-ready at stage {status!r}"
        )


def validate_deployment_run_item(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
) -> None:
    """Require project and delivery-stage compatibility for admission."""
    _validate_deployment_run_item_state(
        conn,
        run_id=run_id,
        item_id=int(item_id),
        state=item_binding_runtime_state(conn, int(item_id)),
        allow_completed=False,
    )


def attached_item_binding_runtime_state(
    conn: Any,
    item_id: int,
) -> tuple[WorkflowRuntime, str] | None:
    """Load an established run member, including later completion.

    New bindings still go through ``item_binding_runtime_state`` and reject
    every terminal item.  An item that was admitted while delivery-ready may
    reach its workflow's successful ``done`` stage before its run starts;
    that completion preserves the established membership.  Engine terminal
    states such as ``cancelled`` and ``stopped`` remain refusals.
    """
    try:
        return item_binding_runtime_state(conn, int(item_id))
    except WorkflowItemBindingError:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT status FROM items WHERE id = {marker}",
            (int(item_id),),
        ).fetchone()
        if row is None:
            raise
        status = str(row["status"] if hasattr(row, "keys") else row[0])
        if status != COMPLETED_ITEM_STAGE_ID:
            raise
        runtime = load_item_workflow_runtime(conn, int(item_id))
        if status not in runtime.terminal_stage_ids:
            raise
        return runtime, status


def validate_attached_deployment_run_item(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
) -> None:
    """Revalidate established membership without re-admitting completed work."""
    _validate_deployment_run_item_state(
        conn,
        run_id=run_id,
        item_id=int(item_id),
        state=attached_item_binding_runtime_state(conn, int(item_id)),
        allow_completed=True,
    )


def validate_deployment_run_items(
    conn: Any,
    *,
    run_id: str,
    item_ids: Iterable[int],
) -> None:
    for item_id in item_ids:
        validate_attached_deployment_run_item(
            conn,
            run_id=run_id,
            item_id=int(item_id),
        )


__all__ = [
    "COMPLETED_ITEM_STAGE_ID",
    "attached_item_binding_runtime_state",
    "delivery_ready_for_stage",
    "validate_attached_deployment_run_item",
    "validate_deployment_run_item",
    "validate_deployment_run_items",
]
