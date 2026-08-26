"""Interpret the pinned workflow when creating item-bound runtime records."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_PATH_CLAIMS_OPTIONAL,
    WORKFLOW_PATH_CLAIMS_REQUIRED,
    WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK,
)
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    ENGINE_WAIT_STAGE_IDS,
    WorkflowRuntime,
    load_item_workflow_runtime,
)
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_PROCESS,
    TARGET_KIND_STEERING,
    WorkClaimTarget,
)

_ITEM_CLAIM_OWNERSHIP_POLICIES = frozenset(
    {
        "single_item_claim",
        "item_claim_and_task_lanes",
        "session_item_and_document_claim",
        "exclusive_session_work_claim",
    }
)
_TASK_CLAIM_OWNERSHIP_POLICY = "item_claim_and_task_lanes"


class WorkflowItemBindingError(ValueError):
    """A new binding is incompatible with the item's current workflow pin."""


def _has_workflow_pin_schema(conn: Any) -> bool:
    return (
        _table_exists(conn, "items")
        and _table_exists(conn, "workflow_versions")
        and all(
            _column_exists(conn, "items", column)
            for column in ("status", "workflow_id", "workflow_version_id")
        )
    )


def item_binding_runtime_state(
    conn: Any,
    item_id: int,
) -> tuple[WorkflowRuntime, str] | None:
    if not _has_workflow_pin_schema(conn):
        return None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT status FROM items WHERE id = {marker}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        raise WorkflowItemBindingError(f"item {item_id} does not exist")
    runtime = load_item_workflow_runtime(conn, int(item_id))
    status = str(row["status"] if hasattr(row, "keys") else row[0])
    if status in runtime.terminal_stage_ids or status in ENGINE_TERMINAL_STAGE_IDS:
        raise WorkflowItemBindingError(
            f"item {item_id} is terminal at workflow stage {status!r}"
        )
    if status not in ENGINE_WAIT_STAGE_IDS:
        if status not in runtime.stage_ids:
            raise WorkflowItemBindingError(
                f"item {item_id} has undeclared workflow stage {status!r}"
            )
        if runtime.skill_for_stage(status) is None:
            raise WorkflowItemBindingError(
                f"workflow stage {status!r} has no active skill"
            )
    return runtime, status


def validate_work_claim_target(conn: Any, target: WorkClaimTarget) -> None:
    """Validate an item/task claim against current ownership policy."""
    if target.kind in {TARGET_KIND_PROCESS, TARGET_KIND_STEERING}:
        return
    item_id = target.item_id if target.kind == TARGET_KIND_ITEM else target.epic_id
    state = item_binding_runtime_state(conn, int(item_id))
    if state is None:
        return
    runtime, _status = state
    ownership = str(runtime.policies["ownership"])
    if target.kind == TARGET_KIND_ITEM:
        if ownership not in _ITEM_CLAIM_OWNERSHIP_POLICIES:
            raise WorkflowItemBindingError(
                f"workflow ownership policy {ownership!r} disallows item claims"
            )
        return
    if target.kind != TARGET_KIND_EPIC_TASK:
        raise WorkflowItemBindingError(f"unsupported claim target {target.kind!r}")
    if (
        ownership != _TASK_CLAIM_OWNERSHIP_POLICY
        or str(runtime.policies["generated_children"]) != "epic_tasks"
    ):
        raise WorkflowItemBindingError(
            f"workflow {runtime.workflow_id}@{runtime.version} does not "
            "permit epic-task claim lanes"
        )
    if _table_exists(conn, "epic_tasks"):
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT 1 FROM epic_tasks WHERE epic_id = {marker} "
            f"AND task_num = {marker}",
            (int(target.epic_id), int(target.task_num)),
        ).fetchone()
        if row is None:
            raise WorkflowItemBindingError(
                f"epic task {target.epic_id}/{target.task_num} does not exist"
            )


def validate_item_path_claim_scope(
    conn: Any,
    item_id: int | None,
    *,
    task_num: int | None = None,
) -> None:
    """Validate an item-level path claim against current path ownership scope."""
    if item_id is None:
        return
    state = item_binding_runtime_state(conn, int(item_id))
    if state is None:
        return
    runtime, _status = state
    policy = str(runtime.policies["path_claims"])
    if policy == WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK:
        if task_num is None:
            raise WorkflowItemBindingError(
                f"workflow {runtime.workflow_id}@{runtime.version} requires "
                "task-scoped path claims"
            )
        if str(runtime.policies["generated_children"]) != "epic_tasks":
            raise WorkflowItemBindingError(
                f"workflow {runtime.workflow_id}@{runtime.version} cannot "
                "bind path claims to Epic tasks"
            )
        return
    if policy not in {
        WORKFLOW_PATH_CLAIMS_OPTIONAL,
        WORKFLOW_PATH_CLAIMS_REQUIRED,
    }:
        raise WorkflowItemBindingError(f"unsupported path-claim policy {policy!r}")


__all__ = [
    "WorkflowItemBindingError",
    "item_binding_runtime_state",
    "validate_item_path_claim_scope",
    "validate_work_claim_target",
]
