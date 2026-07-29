"""Legacy source discovery for the universal item-worktree backfill."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_behavior import (
    LANE_IMPLEMENTATION,
    LANE_INTEGRATION,
    LANE_WORKER,
    worktree_lane_policy,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

_ABSENT_TEXT = frozenset({"", "null"})
_ENGINE_TERMINAL = frozenset({"cancelled", "stopped"})


@dataclass(frozen=True)
class ItemLaneSource:
    item_id: int
    branch: str
    lane_role: str
    released: bool


@dataclass(frozen=True)
class WorkerLaneSource:
    table: str
    row_id: int
    item_id: int
    branch: str
    path: Optional[str]
    released: bool


@dataclass(frozen=True)
class WorkerLanePathResolution:
    path: Optional[str]
    clear_released_path: bool


def clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.casefold() in _ABSENT_TEXT else text


def _terminal_source(conn: Any, item_id: int, status: Any) -> bool:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    item_row = conn.execute(
        f"SELECT status FROM items WHERE id = {marker}",
        (int(item_id),),
    ).fetchone()
    if item_row is None:
        raise AssertionError(f"legacy worktree source item {item_id} does not exist")
    runtime_terminals = {
        stage.casefold()
        for stage in load_item_workflow_runtime(conn, item_id).terminal_stage_ids
    }
    item_status = item_row["status"] if hasattr(item_row, "keys") else item_row[0]
    return any(
        (clean(candidate) or "").casefold()
        in (_ENGINE_TERMINAL | runtime_terminals)
        for candidate in (item_status, status)
    )


def _role_for_item(conn: Any, item_id: int) -> str:
    policy = worktree_lane_policy(load_item_workflow_runtime(conn, item_id))
    if LANE_IMPLEMENTATION in policy.allowed_roles:
        return LANE_IMPLEMENTATION
    return LANE_INTEGRATION


def item_lane_sources(conn: Any) -> list[ItemLaneSource]:
    if not _column_exists(conn, "items", "worktree"):
        return []
    sources: list[ItemLaneSource] = []
    for row in conn.execute(
        "SELECT id, worktree, status FROM items ORDER BY id"
    ).fetchall():
        branch = clean(row[1])
        if branch is None:
            continue
        item_id = int(row[0])
        sources.append(
            ItemLaneSource(
                item_id=item_id,
                branch=branch,
                lane_role=_role_for_item(conn, item_id),
                released=_terminal_source(conn, item_id, row[2]),
            )
        )
    return sources


def _task_lane_sources(conn: Any) -> list[WorkerLaneSource]:
    if not _table_exists(conn, "epic_tasks"):
        return []
    branch_sql = "branch" if _column_exists(conn, "epic_tasks", "branch") else "NULL"
    worktree_sql = (
        "worktree" if _column_exists(conn, "epic_tasks", "worktree") else "NULL"
    )
    path_sql = (
        "worktree_path"
        if _column_exists(conn, "epic_tasks", "worktree_path")
        else "NULL"
    )
    sources: list[WorkerLaneSource] = []
    for row in conn.execute(
        "SELECT id, CAST(epic_id AS INTEGER), "
        + branch_sql
        + ", "
        + worktree_sql
        + ", "
        + path_sql
        + ", status FROM epic_tasks ORDER BY id"
    ).fetchall():
        branch_value = clean(row[2])
        worktree_value = clean(row[3])
        if (
            branch_value is not None
            and worktree_value is not None
            and branch_value != worktree_value
        ):
            raise AssertionError(
                f"epic_tasks id={row[0]} has conflicting legacy branches: "
                f"branch={branch_value!r}, worktree={worktree_value!r}"
            )
        branch = branch_value or worktree_value
        if branch is None:
            continue
        item_id = int(row[1])
        policy = worktree_lane_policy(load_item_workflow_runtime(conn, item_id))
        if LANE_WORKER not in policy.allowed_roles:
            continue
        sources.append(
            WorkerLaneSource(
                table="epic_tasks",
                row_id=int(row[0]),
                item_id=item_id,
                branch=branch,
                path=clean(row[4]),
                released=_terminal_source(conn, item_id, row[5]),
            )
        )
    return sources


def _chain_lane_sources(
    conn: Any,
    task_sources: list[WorkerLaneSource],
) -> list[WorkerLaneSource]:
    if not _table_exists(conn, "epic_dispatch_chains"):
        return []
    worktree_sql = (
        "worktree"
        if _column_exists(conn, "epic_dispatch_chains", "worktree")
        else "NULL"
    )
    path_sql = (
        "worktree_path"
        if _column_exists(conn, "epic_dispatch_chains", "worktree_path")
        else "NULL"
    )
    tasks_by_item: dict[int, list[WorkerLaneSource]] = defaultdict(list)
    for source in task_sources:
        tasks_by_item[source.item_id].append(source)
    sources: list[WorkerLaneSource] = []
    for row in conn.execute(
        "SELECT id, CAST(epic_id AS INTEGER), "
        + worktree_sql
        + ", "
        + path_sql
        + " FROM epic_dispatch_chains ORDER BY id"
    ).fetchall():
        branch = clean(row[2])
        if branch is None:
            continue
        item_id = int(row[1])
        policy = worktree_lane_policy(load_item_workflow_runtime(conn, item_id))
        if LANE_WORKER not in policy.allowed_roles:
            continue
        item_tasks = tasks_by_item[item_id]
        sources.append(
            WorkerLaneSource(
                table="epic_dispatch_chains",
                row_id=int(row[0]),
                item_id=item_id,
                branch=branch,
                path=clean(row[3]),
                released=_terminal_source(conn, item_id, None)
                or (
                    bool(item_tasks)
                    and all(source.released for source in item_tasks)
                ),
            )
        )
    return sources


def worker_lane_sources(conn: Any) -> list[WorkerLaneSource]:
    tasks = _task_lane_sources(conn)
    return tasks + _chain_lane_sources(conn, tasks)


def worker_source_groups(
    sources: list[WorkerLaneSource],
) -> dict[tuple[int, str], list[WorkerLaneSource]]:
    groups: dict[tuple[int, str], list[WorkerLaneSource]] = defaultdict(list)
    for source in sources:
        groups[(source.item_id, source.branch)].append(source)
    for (item_id, branch), group in groups.items():
        resolve_worker_lane_path(item_id, branch, group)
    return dict(groups)


def resolve_worker_lane_path(
    item_id: int,
    branch: str,
    group: list[WorkerLaneSource],
) -> WorkerLanePathResolution:
    concrete_paths = sorted(
        {source.path for source in group if source.path is not None}
    )
    if len(concrete_paths) <= 1:
        return WorkerLanePathResolution(
            path=next(iter(concrete_paths), None),
            clear_released_path=False,
        )
    if all(source.released for source in group):
        return WorkerLanePathResolution(
            path=None,
            clear_released_path=True,
        )
    evidence = ", ".join(
        f"{source.table} id={source.row_id} path={source.path!r}"
        for source in group
        if source.path is not None
    )
    raise AssertionError(
        f"conflicting legacy worktree paths for item {item_id} "
        f"branch {branch!r}: {evidence}"
    )


def assert_source_roles_do_not_conflict(
    item_sources: list[ItemLaneSource],
    worker_sources: list[WorkerLaneSource],
) -> None:
    item_keys = {(source.item_id, source.branch): source for source in item_sources}
    for item_id, branch in worker_source_groups(worker_sources):
        if (item_id, branch) in item_keys:
            raise AssertionError(
                f"legacy branch {branch!r} for item {item_id} is both an "
                "item-owned lane and a worker lane"
            )


__all__ = [
    "ItemLaneSource",
    "WorkerLanePathResolution",
    "WorkerLaneSource",
    "assert_source_roles_do_not_conflict",
    "clean",
    "item_lane_sources",
    "resolve_worker_lane_path",
    "worker_lane_sources",
    "worker_source_groups",
]
