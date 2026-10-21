"""Interpret the pinned workflow when creating item-bound runtime records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_PATH_CLAIMS_OPTIONAL,
    WORKFLOW_PATH_CLAIMS_REQUIRED,
    WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK,
)
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    ENGINE_WAIT_STAGE_IDS,
    WorkflowRuntime,
    workflow_runtime_from_row,
)
from yoke_core.domain.workflow_registry import WorkflowRegistryError
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_PROCESS,
    TARGET_KIND_STEERING,
    WorkClaimTarget,
)
from yoke_contracts.public_ref import ITEM_NOT_FOUND

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


def has_workflow_pin_schema(conn: Any) -> bool:
    return (
        _table_exists(conn, "items")
        and _table_exists(conn, "workflow_versions")
        and all(
            _column_exists(conn, "items", column)
            for column in ("status", "workflow_id", "workflow_version_id")
        )
    )


@dataclass(frozen=True)
class PinnedItem:
    """An item's stage, project and pinned workflow, read together."""

    status: str
    project_id: int
    #: ``None`` when the item has no complete workflow-version pin.
    runtime: WorkflowRuntime | None

    def require_runtime(self, conn: Any, item_id: int) -> WorkflowRuntime:
        """The pinned runtime, or the refusal loading it alone would raise."""
        if self.runtime is None:
            raise WorkflowRegistryError(
                f"{render_item_ref(conn, item_id)} has no complete workflow-version pin"
            )
        return self.runtime


def read_pinned_items(conn: Any, item_ids: Iterable[int]) -> dict[int, PinnedItem]:
    """Read every item's status, project and pinned workflow in one statement.

    An absent item is absent from the result; an incomplete pin refuses when
    that item's runtime is required (:meth:`PinnedItem.require_runtime`).
    """
    ids = sorted({int(value) for value in item_ids})
    if not ids:
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT i.id, i.status, i.project_id, i.workflow_id, "
        "i.workflow_version_id, v.version, v.definition_json, v.definition_digest "
        "FROM items i LEFT JOIN workflow_versions v ON v.id = i.workflow_version_id "
        f"WHERE i.id IN ({','.join(marker for _ in ids)})",
        tuple(ids),
    ).fetchall()
    pinned: dict[int, PinnedItem] = {}
    runtimes: dict[int, WorkflowRuntime] = {}
    for row in sorted((dict(row) for row in rows), key=lambda row: int(row["id"])):
        complete = all(
            row[key] is not None
            for key in ("workflow_id", "workflow_version_id", "version")
        )
        runtime = None
        if complete:
            version_id = int(row["workflow_version_id"])
            if version_id not in runtimes:
                runtimes[version_id] = workflow_runtime_from_row(row)
            runtime = runtimes[version_id]
        pinned[int(row["id"])] = PinnedItem(
            str(row["status"]),
            int(row["project_id"]),
            runtime,
        )
    return pinned


def item_binding_runtime_states(
    conn: Any, item_ids: Iterable[int]
) -> dict[int, tuple[WorkflowRuntime, str]]:
    """Validated binding states for a set of items from one read.

    Refuses on the first item, in id order, that a single-item check refuses.
    Empty when this database has no workflow pins to validate.
    """
    if not has_workflow_pin_schema(conn):
        return {}
    ids = sorted({int(value) for value in item_ids})
    pinned = read_pinned_items(conn, ids)
    return {
        item_id: binding_runtime_state(conn, item_id, pinned.get(item_id))
        for item_id in ids
    }


def item_binding_runtime_state(
    conn: Any,
    item_id: int,
) -> tuple[WorkflowRuntime, str] | None:
    return item_binding_runtime_states(conn, (int(item_id),)).get(int(item_id))


def binding_runtime_state(
    conn: Any, item_id: int, pinned: PinnedItem | None
) -> tuple[WorkflowRuntime, str]:
    """Refuse a new binding on an absent, terminal or undeclared-stage item."""
    if pinned is None:
        raise WorkflowItemBindingError(ITEM_NOT_FOUND)
    runtime, status = pinned.require_runtime(conn, item_id), pinned.status
    if status in runtime.terminal_stage_ids or status in ENGINE_TERMINAL_STAGE_IDS:
        raise WorkflowItemBindingError(
            f"{render_item_ref(conn, item_id)} is terminal at workflow stage {status!r}"
        )
    if status not in ENGINE_WAIT_STAGE_IDS:
        if status not in runtime.stage_ids:
            raise WorkflowItemBindingError(
                f"{render_item_ref(conn, item_id)} has undeclared workflow stage {status!r}"
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
    "PinnedItem",
    "WorkflowItemBindingError",
    "binding_runtime_state",
    "has_workflow_pin_schema",
    "item_binding_runtime_state",
    "item_binding_runtime_states",
    "read_pinned_items",
    "validate_item_path_claim_scope",
    "validate_work_claim_target",
]
