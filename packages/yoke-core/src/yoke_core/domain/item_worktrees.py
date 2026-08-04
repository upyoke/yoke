"""Universal persistence and validation for item-owned worktree lanes."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.workflow_behavior import (
    LANE_IMPLEMENTATION,
    LANE_INTEGRATION,
    LANE_WORKER,
    worktree_lane_policy,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)

LANE_ROLES = frozenset(
    {
        LANE_IMPLEMENTATION,
        LANE_INTEGRATION,
        LANE_WORKER,
    }
)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(value[0]) for value in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def _dict_row(cursor: Any) -> Optional[dict[str, Any]]:
    row = cursor.fetchone()
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    columns = [str(value[0]) for value in cursor.description]
    return dict(zip(columns, row))


def list_item_worktrees(
    conn: Any,
    item_id: int,
    *,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    """Return an item's universal lane records in stable creation order."""
    marker = _placeholder(conn)
    state_clause = " AND state = 'active'" if active_only else ""
    cursor = conn.execute(
        "SELECT id, item_id, branch, path, commit_sha, lane_role, state, "
        "created_at, updated_at, released_at FROM item_worktrees "
        f"WHERE item_id = {marker}{state_clause} ORDER BY id",
        (int(item_id),),
    )
    return _dict_rows(cursor)


def _validate_role_for_item(conn: Any, item_id: int, lane_role: str) -> None:
    if lane_role not in LANE_ROLES:
        raise ValueError(f"unknown item worktree lane role {lane_role!r}")
    runtime = load_item_workflow_runtime(conn, int(item_id))
    if not worktree_lane_policy(runtime).allows(lane_role):
        raise ValueError(
            f"workflow {runtime.workflow_id}@{runtime.version} does not allow "
            f"{lane_role!r} worktree lanes"
        )


def record_item_worktree(
    conn: Any,
    *,
    item_id: int,
    branch: str,
    path: Optional[str],
    lane_role: str,
    validate_policy: bool = True,
) -> dict[str, Any]:
    """Create or refresh one active lane while preserving released history."""
    clean_branch = branch.strip()
    clean_path = (path or "").strip() or None
    if not clean_branch:
        raise ValueError("item worktree branch must be non-empty")
    lock_item_workflow_bindings(conn, (int(item_id),))
    from yoke_core.domain.item_terminal_resources import (
        ensure_item_accepts_active_resources,
    )

    ensure_item_accepts_active_resources(conn, int(item_id))
    if validate_policy:
        _validate_role_for_item(conn, int(item_id), lane_role)
    elif lane_role not in LANE_ROLES:
        raise ValueError(f"unknown item worktree lane role {lane_role!r}")

    marker = _placeholder(conn)
    if clean_path is not None:
        owner_cursor = conn.execute(
            "SELECT item_id, branch FROM item_worktrees "
            f"WHERE path = {marker} AND state = 'active'",
            (clean_path,),
        )
        owner = _dict_row(owner_cursor)
        if owner is not None and (
            int(owner["item_id"]) != int(item_id)
            or str(owner["branch"]) != clean_branch
        ):
            raise ValueError(
                f"active worktree path {clean_path!r} is already owned by "
                f"item {owner['item_id']} branch {owner['branch']!r}"
            )

    now = iso8601_now()
    existing_cursor = conn.execute(
        "SELECT id FROM item_worktrees "
        f"WHERE item_id = {marker} AND branch = {marker} "
        "AND state = 'active'",
        (int(item_id), clean_branch),
    )
    existing = _dict_row(existing_cursor)
    if existing is not None:
        conn.execute(
            "UPDATE item_worktrees "
            f"SET path = {marker}, "
            f"lane_role = {marker}, updated_at = {marker} "
            f"WHERE id = {marker}",
            (clean_path, lane_role, now, int(existing["id"])),
        )
    else:
        if lane_role in {LANE_IMPLEMENTATION, LANE_INTEGRATION}:
            conn.execute(
                "UPDATE item_worktrees SET state = 'released', "
                f"released_at = {marker}, updated_at = {marker} "
                f"WHERE item_id = {marker} AND lane_role = {marker} "
                "AND state = 'active'",
                (now, now, int(item_id), lane_role),
            )
        conn.execute(
            "INSERT INTO item_worktrees "
            "(item_id, branch, path, lane_role, state, "
            "created_at, updated_at, released_at) "
            f"VALUES ({', '.join(marker for _ in range(4))}, "
            f"'active', {marker}, {marker}, NULL)",
            (
                int(item_id),
                clean_branch,
                clean_path,
                lane_role,
                now,
                now,
            ),
        )

    rows = list_item_worktrees(conn, int(item_id), active_only=True)
    return next(row for row in rows if row["branch"] == clean_branch)


def record_released_item_worktree_history(
    conn: Any,
    *,
    item_id: int,
    branch: str,
    path: Optional[str],
    lane_role: str,
) -> dict[str, Any]:
    """Persist migration history without ever creating an active lane."""
    clean_branch = branch.strip()
    clean_path = (path or "").strip() or None
    if not clean_branch:
        raise ValueError("item worktree branch must be non-empty")
    if lane_role not in LANE_ROLES:
        raise ValueError(f"unknown item worktree lane role {lane_role!r}")
    lock_item_workflow_bindings(conn, (int(item_id),))
    marker = _placeholder(conn)
    now = iso8601_now()
    existing = _dict_row(
        conn.execute(
            "SELECT id FROM item_worktrees "
            f"WHERE item_id={marker} AND branch={marker} "
            "ORDER BY CASE WHEN state='active' THEN 0 ELSE 1 END, id DESC "
            "LIMIT 1",
            (int(item_id), clean_branch),
        )
    )
    if existing is None:
        cursor = conn.execute(
            "INSERT INTO item_worktrees "
            "(item_id, branch, path, lane_role, state, created_at, "
            "updated_at, released_at) "
            f"VALUES ({', '.join(marker for _ in range(4))}, "
            f"'released', {marker}, {marker}, {marker}) RETURNING id",
            (
                int(item_id),
                clean_branch,
                clean_path,
                lane_role,
                now,
                now,
                now,
            ),
        )
        lane_id = int(cursor.fetchone()[0])
    else:
        lane_id = int(existing["id"])
        conn.execute(
            "UPDATE item_worktrees SET path="
            f"{marker}, lane_role={marker}, state='released', "
            f"updated_at={marker}, released_at={marker} WHERE id={marker}",
            (clean_path, lane_role, now, now, lane_id),
        )
    return next(
        row
        for row in list_item_worktrees(conn, int(item_id))
        if int(row["id"]) == lane_id
    )


def release_item_worktrees(
    conn: Any,
    *,
    item_id: int,
    branch: Optional[str] = None,
) -> int:
    """Release one branch or every active lane owned by an item."""
    lock_item_workflow_bindings(conn, (int(item_id),))
    marker = _placeholder(conn)
    params: list[Any] = [iso8601_now(), iso8601_now(), int(item_id)]
    branch_clause = ""
    if branch is not None:
        branch_clause = f" AND branch = {marker}"
        params.append(branch)
    cursor = conn.execute(
        "UPDATE item_worktrees SET state = 'released', "
        f"released_at = {marker}, updated_at = {marker} "
        f"WHERE item_id = {marker} AND state = 'active'{branch_clause}",
        tuple(params),
    )
    return max(int(cursor.rowcount or 0), 0)


def record_worker_item_worktree(
    conn: Any,
    *,
    item_id: int,
    branch: str,
    path: Optional[str],
) -> dict[str, Any]:
    """Record a worker lane and materialize its required integration peer."""
    worker = record_item_worktree(
        conn,
        item_id=item_id,
        branch=branch,
        path=path,
        lane_role=LANE_WORKER,
    )
    runtime = load_item_workflow_runtime(conn, int(item_id))
    policy = worktree_lane_policy(runtime)
    if LANE_INTEGRATION not in policy.required_roles:
        return worker
    active = list_item_worktrees(conn, int(item_id), active_only=True)
    if any(row["lane_role"] == LANE_INTEGRATION for row in active):
        return worker
    from yoke_core.domain.worktree_naming import worktree_name_for_item

    integration_branch = worktree_name_for_item(conn, item_id)
    if any(row["branch"] == integration_branch for row in active):
        integration_branch += "-integration"
    record_item_worktree(
        conn,
        item_id=item_id,
        branch=integration_branch,
        path=None,
        lane_role=LANE_INTEGRATION,
    )
    return worker


def primary_item_worktree(
    conn: Any,
    item_id: int,
    *,
    lane_role: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Return one active lane, optionally constrained to a lane role."""
    rows = list_item_worktrees(conn, int(item_id), active_only=True)
    if lane_role is not None:
        rows = [row for row in rows if row["lane_role"] == lane_role]
    return rows[0] if rows else None


def validate_item_worktree_roles(conn: Any, item_id: int) -> None:
    """Reject active lanes that violate the item's immutable workflow policy."""
    runtime = load_item_workflow_runtime(conn, int(item_id))
    policy = worktree_lane_policy(runtime)
    active = list_item_worktrees(conn, int(item_id), active_only=True)
    roles = {str(row["lane_role"]) for row in active}
    disallowed = roles - policy.allowed_roles
    if disallowed:
        raise ValueError(
            f"item {item_id} has lanes disallowed by "
            f"{runtime.workflow_id}@{runtime.version}: {sorted(disallowed)}"
        )
    if active:
        missing = policy.required_roles - roles
        if missing:
            raise ValueError(
                f"item {item_id} lacks required worktree lanes for "
                f"{runtime.workflow_id}@{runtime.version}: {sorted(missing)}"
            )


__all__ = [
    "LANE_ROLES",
    "list_item_worktrees",
    "primary_item_worktree",
    "record_released_item_worktree_history",
    "record_item_worktree",
    "record_worker_item_worktree",
    "release_item_worktrees",
    "validate_item_worktree_roles",
]
