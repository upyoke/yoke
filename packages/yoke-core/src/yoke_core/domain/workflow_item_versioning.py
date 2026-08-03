"""Inspection and explicit compatible migration of item workflow pins."""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.item_worktrees import list_item_worktrees
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_behavior import (
    worktree_lane_policy,
    worktree_lane_policy_for_id,
)
from yoke_core.domain.workflow_definition_codec import (
    WorkflowRegistryError,
)
from yoke_core.domain.workflow_item_migration_compatibility import (
    item_migration_binding_conflicts,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_core.domain.workflow_effective_policies import (
    resolve_effective_workflow_policies,
)
from yoke_core.domain.workflow_runtime import (
    ENGINE_EXCEPTIONAL_STAGE_IDS,
    ENGINE_TERMINAL_STAGE_IDS,
    WorkflowRuntime,
    load_item_workflow_runtime,
    workflow_runtime_from_row,
)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _dict_row(cursor: Any) -> Optional[dict[str, Any]]:
    row = cursor.fetchone()
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    columns = [str(value[0]) for value in cursor.description]
    return dict(zip(columns, row))


def _inspect_item_workflow_pin(
    conn: Any,
    item_id: int,
    runtime: WorkflowRuntime,
) -> dict[str, Any]:
    marker = _placeholder(conn)
    item = _dict_row(
        conn.execute(
            f"SELECT status, workflow_posture FROM items WHERE id = {marker}",
            (int(item_id),),
        )
    )
    if item is None:
        raise WorkflowRegistryError(f"item {item_id} does not exist")
    policy = worktree_lane_policy(runtime)
    lanes = (
        list_item_worktrees(conn, int(item_id), active_only=True)
        if _table_exists(conn, "item_worktrees")
        else []
    )
    posture = json.loads(str(item["workflow_posture"] or "{}"))
    effective = resolve_effective_workflow_policies(runtime, posture)
    return {
        "item_id": int(item_id),
        "workflow_id": runtime.workflow_id,
        "workflow_version": runtime.version,
        "workflow_version_id": runtime.workflow_version_id,
        "definition_digest": runtime.definition_digest,
        "status": str(item["status"]),
        "workflow_posture": posture,
        "policies": dict(runtime.policies),
        "effective_policies": dict(effective.values),
        "worktree_policy": str(runtime.policies["worktrees"]),
        "allowed_lane_roles": sorted(policy.allowed_roles),
        "required_lane_roles": sorted(policy.required_roles),
        "active_lanes": lanes,
    }


def inspect_item_workflow_pin(conn: Any, item_id: int) -> dict[str, Any]:
    """Return the exact immutable version and interpreted lane policy."""
    runtime = load_item_workflow_runtime(conn, int(item_id))
    return _inspect_item_workflow_pin(conn, int(item_id), runtime)


def _target_version_row(
    conn: Any,
    *,
    workflow_id: str,
    version: Optional[int],
) -> dict[str, Any]:
    marker = _placeholder(conn)
    if version is None:
        cursor = conn.execute(
            "SELECT v.id AS workflow_version_id, v.workflow_id, v.version, "
            "v.definition_json, v.definition_digest "
            "FROM workflows w JOIN workflow_versions v "
            "ON v.id = w.current_version_id "
            f"WHERE w.id = {marker}",
            (workflow_id,),
        )
    else:
        cursor = conn.execute(
            "SELECT id AS workflow_version_id, workflow_id, version, "
            "definition_json, definition_digest FROM workflow_versions "
            f"WHERE workflow_id = {marker} AND version = {marker}",
            (workflow_id, int(version)),
        )
    row = _dict_row(cursor)
    if row is None:
        suffix = "current" if version is None else str(version)
        raise WorkflowRegistryError(f"unknown workflow version {workflow_id}@{suffix}")
    return row


def _mapped_status(
    *,
    current_status: str,
    current_version: int,
    target_version: int,
    target_definition: Mapping[str, Any],
) -> str:
    target_stages = {str(stage["id"]) for stage in target_definition["stages"]}
    if (
        current_status in target_stages
        or current_status in ENGINE_EXCEPTIONAL_STAGE_IDS
    ):
        return current_status
    mapping = target_definition.get("stage_mapping")
    if (
        target_version != current_version + 1
        or not isinstance(mapping, Mapping)
        or current_status not in mapping
    ):
        raise WorkflowRegistryError(
            f"stage {current_status!r} cannot be mapped safely from version "
            f"{current_version} to {target_version}"
        )
    return str(mapping[current_status])


def _implementation_entry_reached(
    runtime: WorkflowRuntime,
    stage_id: str,
) -> bool:
    """Whether a nonterminal stage must satisfy implementation-lane policy."""
    from yoke_core.domain.workflow_definition_builders import (
        IMPLEMENTATION_WORKFLOW_SKILL_IDS,
    )

    if stage_id in runtime.terminal_stage_ids or stage_id in ENGINE_TERMINAL_STAGE_IDS:
        return False
    current = runtime.stage_index(stage_id)
    if current is None:
        return True
    starts = [
        runtime.stage_index(str(binding["from_stage_id"]))
        for binding in runtime.definition["skill_bindings"]
        if str(binding["skill_id"]) in IMPLEMENTATION_WORKFLOW_SKILL_IDS
    ]
    positions = [position for position in starts if position is not None]
    return bool(positions) and current > min(positions)


def _ensure_terminal_semantics_preserved(
    *,
    source: WorkflowRuntime,
    source_stage: str,
    target: WorkflowRuntime,
    target_stage: str,
) -> None:
    """Reject version moves that implicitly terminate or resurrect an item."""
    source_terminal = (
        source_stage in source.terminal_stage_ids
        or source_stage in ENGINE_TERMINAL_STAGE_IDS
    )
    target_terminal = (
        target_stage in target.terminal_stage_ids
        or target_stage in ENGINE_TERMINAL_STAGE_IDS
    )
    if source_terminal == target_terminal:
        return
    direction = (
        "non-terminal to terminal" if target_terminal else "terminal to non-terminal"
    )
    raise WorkflowRegistryError(
        "workflow-version migration cannot change item terminal semantics "
        f"({direction}): {source_stage!r} -> {target_stage!r}"
    )


def migrate_item_workflow_pin(
    conn: Any,
    *,
    item_id: int,
    target_version: Optional[int] = None,
) -> dict[str, Any]:
    """Move one item to a compatible version of its existing workflow."""
    try:
        lock_item_workflow_bindings(conn, (int(item_id),))
        source_runtime = load_item_workflow_runtime(conn, int(item_id))
        before = _inspect_item_workflow_pin(conn, int(item_id), source_runtime)
        target = _target_version_row(
            conn,
            workflow_id=str(before["workflow_id"]),
            version=target_version,
        )
        if int(target["workflow_version_id"]) == int(before["workflow_version_id"]):
            conn.commit()
            return {"changed": False, "before": before, "after": before}

        target_runtime = workflow_runtime_from_row(target)
        definition = target_runtime.definition
        posture = before["workflow_posture"]
        allowed_posture = set(definition["policies"]["item_posture_allowlist"])
        unknown_posture = set(posture) - allowed_posture
        if unknown_posture:
            raise WorkflowRegistryError(
                "target workflow version disallows item posture keys: "
                f"{sorted(unknown_posture)}"
            )

        new_status = _mapped_status(
            current_status=str(before["status"]),
            current_version=int(before["workflow_version"]),
            target_version=int(target["version"]),
            target_definition=definition,
        )
        _ensure_terminal_semantics_preserved(
            source=source_runtime,
            source_stage=str(before["status"]),
            target=target_runtime,
            target_stage=new_status,
        )
        target_policy = worktree_lane_policy_for_id(
            str(definition["policies"]["worktrees"])
        )
        source_policy = worktree_lane_policy(source_runtime)
        lane_roles = {str(row["lane_role"]) for row in before["active_lanes"]}
        disallowed = lane_roles - target_policy.allowed_roles
        missing = target_policy.required_roles - lane_roles if lane_roles else set()
        if (
            not lane_roles
            and source_policy != target_policy
            and _implementation_entry_reached(target_runtime, new_status)
        ):
            missing = target_policy.required_roles
        if disallowed or missing:
            raise WorkflowRegistryError(
                "target workflow version is incompatible with active worktree "
                f"lanes; disallowed={sorted(disallowed)} "
                f"missing={sorted(missing)}"
            )

        binding_conflicts = item_migration_binding_conflicts(
            conn,
            item_id=int(item_id),
            source=source_runtime,
            target=target_runtime,
            source_stage=str(before["status"]),
            target_stage=new_status,
            posture=posture,
        )
        if binding_conflicts:
            raise WorkflowRegistryError(
                "target workflow version is incompatible with live item bindings: "
                + "; ".join(binding_conflicts)
            )

        marker = _placeholder(conn)
        conn.execute(
            f"UPDATE items SET workflow_version_id = {marker}, status = {marker} "
            f"WHERE id = {marker}",
            (int(target["workflow_version_id"]), new_status, int(item_id)),
        )
        after = _inspect_item_workflow_pin(
            conn,
            int(item_id),
            target_runtime,
        )
        conn.commit()
        return {
            "changed": True,
            "before": before,
            "after": after,
        }
    except Exception:
        conn.rollback()
        raise


__all__ = [
    "inspect_item_workflow_pin",
    "migrate_item_workflow_pin",
]
