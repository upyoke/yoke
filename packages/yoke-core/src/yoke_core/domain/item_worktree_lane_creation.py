"""Claimed-item registration of workflow worktree lanes."""

from __future__ import annotations

from typing import Any

from yoke_contracts.git_ref_name import branch_validation_error
from yoke_contracts.item_worktrees import (
    ADDITIONAL_ITEM_WORKTREE_LANE_ROLES,
)
from yoke_core.domain import db_backend
from yoke_core.domain.item_terminal_resources import (
    ensure_item_accepts_active_resources,
)
from yoke_core.domain.item_worktrees import (
    list_item_worktrees,
    record_item_worktree,
    validate_item_worktree_roles,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_behavior import (
    LANE_INTEGRATION,
    LANE_WORKER,
    worktree_lane_policy,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


ADDITIONAL_LANE_ROLES = frozenset(ADDITIONAL_ITEM_WORKTREE_LANE_ROLES)


class ItemWorktreeLaneCreationError(ValueError):
    """An explicit additional lane conflicts with item or lane policy."""


def _project_scope_column(conn: Any) -> str | None:
    if _column_exists(conn, "items", "project_id"):
        return "project_id"
    if _column_exists(conn, "items", "project"):
        return "project"
    return None


def _lock_project_scope(conn: Any, item_id: int, column: str | None) -> None:
    """Serialize explicit branch selection within one project when possible."""
    if column != "project_id" or not _table_exists(conn, "projects"):
        return
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id = {marker}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return
    project_id = row["project_id"] if hasattr(row, "keys") else row[0]
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    conn.execute(
        f"SELECT id FROM projects WHERE id = {marker}{suffix}",
        (project_id,),
    ).fetchall()


def _same_project_branch_owner(
    conn: Any,
    *,
    item_id: int,
    branch: str,
    project_column: str | None,
) -> int | None:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    if project_column is None:
        project_clause = ""
    else:
        project_clause = (
            f" AND owner_item.{project_column} = target_item.{project_column}"
        )
    row = conn.execute(
        "SELECT lane.item_id FROM item_worktrees AS lane "
        "JOIN items AS owner_item ON owner_item.id = lane.item_id "
        f"JOIN items AS target_item ON target_item.id = {marker} "
        f"WHERE lane.branch = {marker} AND lane.state = 'active' "
        f"AND lane.item_id <> {marker}{project_clause} "
        "ORDER BY lane.item_id LIMIT 1",
        (int(item_id), branch, int(item_id)),
    ).fetchone()
    if row is None:
        return None
    value = row["item_id"] if hasattr(row, "keys") else row[0]
    return int(value)


@rollback_workflow_binding_write_errors
def _register_item_worktree_lane(
    conn: Any,
    *,
    item_id: int,
    lane_role: str,
    branch: str,
    commit: bool = True,
) -> dict[str, Any]:
    """Register one policy-allowed lane for local provisioning.

    The universal worktree creator derives the machine-local path from this
    branch on its next preparation pass. The ordinary default-lane flow stays
    separate and chooses its workflow-defined branch before calling here.
    """
    branch_error = branch_validation_error(branch)
    if branch_error is not None:
        raise ItemWorktreeLaneCreationError(branch_error)

    item_id = int(item_id)
    lock_item_workflow_bindings(conn, (item_id,))
    ensure_item_accepts_active_resources(conn, item_id)
    runtime = load_item_workflow_runtime(conn, item_id)
    policy = worktree_lane_policy(runtime)
    if not policy.allows(lane_role):
        raise ItemWorktreeLaneCreationError(
            f"workflow {runtime.workflow_id}@{runtime.version} does not allow "
            f"{lane_role!r} worktree lanes"
        )

    project_column = _project_scope_column(conn)
    _lock_project_scope(conn, item_id, project_column)
    active = list_item_worktrees(conn, item_id, active_only=True)
    if not active and policy.required_roles != frozenset({lane_role}):
        raise ItemWorktreeLaneCreationError(
            "prepare the workflow's default worktree lane before registering "
            "an additional lane; only its sole policy-required role may be "
            "the first active lane"
        )
    if active:
        try:
            validate_item_worktree_roles(conn, item_id)
        except ValueError as exc:
            raise ItemWorktreeLaneCreationError(
                f"existing active lanes violate the pinned workflow: {exc}"
            ) from exc

    branch_owner = _same_project_branch_owner(
        conn,
        item_id=item_id,
        branch=branch,
        project_column=project_column,
    )
    if branch_owner is not None:
        raise ItemWorktreeLaneCreationError(
            f"active branch {branch!r} is already registered to item "
            f"{branch_owner} in this project"
        )

    same_branch = next(
        (lane for lane in active if str(lane["branch"]) == branch),
        None,
    )
    if same_branch is not None:
        if str(same_branch["lane_role"]) != lane_role:
            raise ItemWorktreeLaneCreationError(
                f"active branch {branch!r} is already registered as "
                f"{same_branch['lane_role']!r}"
            )
        if commit:
            conn.commit()
        return same_branch

    if lane_role == LANE_INTEGRATION:
        integration = next(
            (lane for lane in active if str(lane["lane_role"]) == LANE_INTEGRATION),
            None,
        )
        if integration is not None:
            raise ItemWorktreeLaneCreationError(
                f"item already has active integration branch {integration['branch']!r}"
            )

    lane = record_item_worktree(
        conn,
        item_id=item_id,
        branch=branch,
        path=None,
        lane_role=lane_role,
    )
    if commit:
        conn.commit()
    return lane


@rollback_workflow_binding_write_errors
def create_additional_item_worktree_lane(
    conn: Any,
    *,
    item_id: int,
    lane_role: str,
    branch: str,
    commit: bool = True,
) -> dict[str, Any]:
    """Register one explicit worker or integration lane."""
    if lane_role not in ADDITIONAL_LANE_ROLES:
        raise ItemWorktreeLaneCreationError(
            "additional item worktree lanes must use role "
            f"{LANE_WORKER!r} or {LANE_INTEGRATION!r}"
        )
    return _register_item_worktree_lane(
        conn,
        item_id=item_id,
        lane_role=lane_role,
        branch=branch,
        commit=commit,
    )


def ensure_default_item_worktree_lane(
    conn: Any,
    *,
    item_id: int,
    commit: bool = True,
) -> dict[str, Any]:
    """Return or register the sole policy-required default lane."""
    item_id = int(item_id)
    lock_item_workflow_bindings(conn, (item_id,))
    ensure_item_accepts_active_resources(conn, item_id)
    runtime = load_item_workflow_runtime(conn, item_id)
    policy = worktree_lane_policy(runtime)
    active = list_item_worktrees(conn, item_id, active_only=True)
    if len(policy.required_roles) != 1:
        present_roles = {str(lane["lane_role"]) for lane in active}
        if active and policy.required_roles.issubset(present_roles):
            primary = min(
                active,
                key=lambda lane: (
                    0 if str(lane["lane_role"]) == LANE_INTEGRATION else 1,
                    int(lane["id"]),
                ),
            )
            if commit:
                conn.commit()
            return primary
        raise ItemWorktreeLaneCreationError(
            f"workflow {runtime.workflow_id}@{runtime.version} does not have "
            "one unambiguous policy-required default worktree lane"
        )
    lane_role = next(iter(policy.required_roles))
    existing = next(
        (lane for lane in active if str(lane["lane_role"]) == lane_role),
        None,
    )
    if existing is not None:
        if commit:
            conn.commit()
        return existing
    from yoke_core.domain.worktree_naming import worktree_name_for_item

    return _register_item_worktree_lane(
        conn,
        item_id=item_id,
        lane_role=lane_role,
        branch=worktree_name_for_item(conn, item_id),
        commit=commit,
    )


__all__ = [
    "ADDITIONAL_LANE_ROLES",
    "ItemWorktreeLaneCreationError",
    "create_additional_item_worktree_lane",
    "ensure_default_item_worktree_lane",
]
