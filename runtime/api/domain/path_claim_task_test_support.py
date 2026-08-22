"""Seed helpers for task-scoped path-claim behavior tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.api.fixtures.backlog_inserts import (
    insert_epic_task,
    insert_item,
    insert_item_worktree,
)
from runtime.api.domain._path_claims_test_helpers import local_human
from yoke_core.domain.db_helpers import iso8601_now


def seed_epic(conn: Any, *, item_id: int, status: str = "planned") -> int:
    """Insert one item pinned to the built-in Epic workflow."""
    insert_item(
        conn,
        id=item_id,
        workflow_id="epic",
        status=status,
        title="Task-scoped claim test",
    )
    return item_id


def seed_worker_task(
    conn: Any,
    *,
    item_id: int,
    task_num: int,
    lane_path: Path,
    task_status: str = "planned",
    budget_path: str | None = None,
) -> int:
    """Insert one worker lane, generated task, and optional persisted budget."""
    lane_path.mkdir(parents=True, exist_ok=True)
    lane = insert_item_worktree(
        conn,
        item_id=item_id,
        branch=f"task-{task_num}",
        lane_role="worker",
        path=str(lane_path),
    )
    insert_epic_task(
        conn,
        epic_id=item_id,
        task_num=task_num,
        status=task_status,
        item_worktree_id=int(lane["id"]),
    )
    if budget_path is not None:
        conn.execute(
            "INSERT INTO epic_task_files "
            "(epic_id, task_num, file_path, action) "
            "VALUES (%s, %s, %s, 'modify')",
            (item_id, task_num, budget_path),
        )
        conn.commit()
    return int(lane["id"])


def seed_integration_lane(conn: Any, *, item_id: int, lane_path: Path) -> int:
    """Insert one active integration lane with a physical path."""
    lane_path.mkdir(parents=True, exist_ok=True)
    lane = insert_item_worktree(
        conn,
        item_id=item_id,
        branch=f"integrate-{item_id}",
        lane_role="integration",
        path=str(lane_path),
    )
    return int(lane["id"])


def seed_target(
    conn: Any,
    *,
    item_id: int,
    path: str,
    kind: str = "file",
) -> int:
    """Insert one observed path-registry target for the item's project."""
    project_id = int(
        conn.execute(
            "SELECT project_id FROM items WHERE id = %s",
            (item_id,),
        ).fetchone()[0]
    )
    row = conn.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, created_at) "
        "VALUES (%s, %s, %s, 1, %s) RETURNING id",
        (project_id, kind, path, iso8601_now()),
    ).fetchone()
    conn.commit()
    return int(row[0])


def seed_item_claim(
    conn: Any,
    *,
    item_id: int,
    target_ids: tuple[int, ...],
    state: str = "active",
) -> int:
    """Insert an item-owned claim, targets, and activation facts."""
    now = iso8601_now()
    row = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, owner_kind, owner_item_id, registered_by_actor_id, "
        "integration_target, registered_at, "
        "activated_at, base_commit_sha) "
        "VALUES (%s, 'exclusive', 'item', %s, %s, 'main', "
        "%s, %s, %s) RETURNING id",
        (
            state,
            item_id,
            local_human(conn),
            now,
            now if state == "active" else None,
            "test-base" if state == "active" else None,
        ),
    ).fetchone()
    claim_id = int(row[0])
    for target_id in target_ids:
        conn.execute(
            "INSERT INTO path_claim_targets "
            "(claim_id, target_id, declared_at) VALUES (%s, %s, %s)",
            (claim_id, target_id, now),
        )
    conn.commit()
    return claim_id


def bind_claim(conn: Any, *, claim_id: int, item_id: int, task_num: int) -> None:
    """Insert one explicit durable task binding."""
    conn.execute(
        "INSERT INTO path_claim_task_bindings "
        "(claim_id, epic_id, task_num, bound_at) VALUES (%s, %s, %s, %s)",
        (claim_id, item_id, task_num, iso8601_now()),
    )
    conn.commit()


def seed_session(
    conn: Any,
    *,
    session_id: str,
    item_id: int,
    task_num: int | None = None,
) -> None:
    """Insert a current-item session plus parent and optional task work claims."""
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, project_id, execution_lane, "
        "executor_version, machine_id, workspace, mode, offered_at, last_heartbeat, actor_id, "
        "current_item_id) "
        "VALUES (%s, 'claude-code', 'test', 'test', "
        "(SELECT project_id FROM items WHERE id = %s), 'primary', NULL, NULL, "
        "'/tmp', 'active', %s, %s, %s, %s)",
        (
            session_id,
            item_id,
            now,
            now,
            local_human(conn),
            str(item_id),
        ),
    )
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claimed_at, last_heartbeat) "
        "VALUES (%s, 'item', %s, %s, %s)",
        (session_id, item_id, now, now),
    )
    if task_num is not None:
        conn.execute(
            "INSERT INTO work_claims "
            "(session_id, target_kind, epic_id, task_num, "
            "claimed_at, last_heartbeat) "
            "VALUES (%s, 'epic_task', %s, %s, %s, %s)",
            (session_id, item_id, task_num, now, now),
        )
    conn.commit()


__all__ = [
    "bind_claim",
    "seed_epic",
    "seed_integration_lane",
    "seed_item_claim",
    "seed_session",
    "seed_target",
    "seed_worker_task",
]
