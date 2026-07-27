"""Record universal item-worktree lanes from normalized legacy sources."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.item_worktrees import list_item_worktrees, record_item_worktree
from yoke_core.domain.migrations.workflow_item_worktree_sources import (
    ItemLaneSource,
    WorkerLaneSource,
    clean,
    resolve_worker_lane_path,
    worker_source_groups,
)
from yoke_core.domain.workflow_behavior import (
    LANE_INTEGRATION,
    LANE_WORKER,
    worktree_lane_policy,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _record_lane(
    conn: Any,
    *,
    item_id: int,
    branch: str,
    path: Optional[str],
    lane_role: str,
    released: bool,
    clear_released_path: bool = False,
) -> int:
    if clear_released_path and not released:
        raise AssertionError("only released lane history may discard a legacy path")
    marker = _placeholder(conn)
    prior = conn.execute(
        "SELECT id, path, lane_role, state FROM item_worktrees WHERE item_id="
        + marker
        + " AND branch="
        + marker
        + " ORDER BY CASE WHEN state='active' THEN 0 ELSE 1 END, id DESC LIMIT 1",
        (item_id, branch),
    ).fetchone()
    effective_path = None if clear_released_path else path
    if prior is not None:
        prior_path = clean(prior[1])
        prior_role = str(prior[2])
        prior_state = str(prior[3])
        if prior_role != lane_role and (prior_state == "active" or released):
            raise AssertionError(
                f"legacy branch {branch!r} for item {item_id} conflicts with "
                f"existing {prior_role!r} lane role"
            )
        if (
            not clear_released_path
            and prior_path is not None
            and path is not None
            and prior_path != path
        ):
            raise AssertionError(
                f"legacy branch {branch!r} for item {item_id} has path {path!r}, "
                f"but its existing lane has path {prior_path!r}"
            )
        effective_path = None if clear_released_path else path or prior_path
        if prior_state == ("released" if released else "active"):
            if clear_released_path and prior_path is not None:
                conn.execute(
                    "UPDATE item_worktrees SET path=NULL, updated_at="
                    + marker
                    + " WHERE id="
                    + marker,
                    (iso8601_now(), int(prior[0])),
                )
            elif path is not None and prior_path is None:
                conn.execute(
                    "UPDATE item_worktrees SET path="
                    + marker
                    + ", updated_at="
                    + marker
                    + " WHERE id="
                    + marker,
                    (path, iso8601_now(), int(prior[0])),
                )
            return int(prior[0])
    lane = record_item_worktree(
        conn,
        item_id=item_id,
        branch=branch,
        path=effective_path,
        lane_role=lane_role,
        validate_policy=False,
    )
    if released and lane["state"] == "active":
        now = iso8601_now()
        conn.execute(
            "UPDATE item_worktrees SET state='released', released_at="
            f"{marker}, updated_at={marker} WHERE id={marker}",
            (now, now, int(lane["id"])),
        )
    return int(lane["id"])


def backfill_item_lanes(
    conn: Any,
    sources: list[ItemLaneSource],
) -> None:
    for source in sources:
        _record_lane(
            conn,
            item_id=source.item_id,
            branch=source.branch,
            path=None,
            lane_role=source.lane_role,
            released=source.released,
        )


def backfill_worker_lanes(
    conn: Any,
    sources: list[WorkerLaneSource],
) -> None:
    marker = _placeholder(conn)
    for (item_id, branch), group in sorted(worker_source_groups(sources).items()):
        path_resolution = resolve_worker_lane_path(item_id, branch, group)
        lane_id = _record_lane(
            conn,
            item_id=item_id,
            branch=branch,
            path=path_resolution.path,
            lane_role=LANE_WORKER,
            released=all(source.released for source in group),
            clear_released_path=path_resolution.clear_released_path,
        )
        for source in group:
            conn.execute(
                f"UPDATE {source.table} SET item_worktree_id={marker} "
                f"WHERE id={marker}",
                (lane_id, source.row_id),
            )


def ensure_required_peers(conn: Any) -> None:
    """Create required integration peers for active worker lanes."""
    for (item_id,) in conn.execute(
        "SELECT DISTINCT item_id FROM item_worktrees "
        "WHERE lane_role='worker' AND state='active' ORDER BY item_id"
    ).fetchall():
        item_id = int(item_id)
        policy = worktree_lane_policy(load_item_workflow_runtime(conn, item_id))
        active = list_item_worktrees(conn, item_id, active_only=True)
        if LANE_INTEGRATION in policy.required_roles and not any(
            row["lane_role"] == LANE_INTEGRATION for row in active
        ):
            _record_lane(
                conn,
                item_id=item_id,
                branch=f"YOK-{item_id}-integration",
                path=None,
                lane_role=LANE_INTEGRATION,
                released=False,
            )


__all__ = ["backfill_item_lanes", "backfill_worker_lanes", "ensure_required_peers"]
