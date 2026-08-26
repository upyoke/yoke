"""Shared Postgres seeds for the session-cwd lint test family.

The lint resolves a session's authority from active ``work_claims``
joined to ``items`` / ``epic_tasks`` plus the machine checkout map.
These helpers seed that shape on a disposable Postgres test database
(:func:`runtime.api.fixtures.pg_testdb.test_database`), whose fixture
schema pre-seeds the ``yoke`` (id 1) and ``externalwebapp`` (id 2) project rows.

Items default to ``status='implementing'`` so the pre-implementing
status gate stays inert for tests whose subject is the scope check;
the status-gate tests pass their status explicitly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.api.fixtures.backlog_inserts import (
    insert_epic_task,
    insert_item,
    insert_item_worktree,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.work_claim_targets import (
    make_epic_task_target,
    make_item_target,
)

_PROJECT_IDS = {"yoke": 1, "externalwebapp": 2}


def project_id(project: str = "yoke") -> int:
    return _PROJECT_IDS.get(project, 100)


def seed_item(
    conn: Any,
    *,
    item_id: int,
    branch: "str | None",
    repo_path: "Any | None" = None,
    project: str = "yoke",
    status: str = "implementing",
    workflow_id: str = "issue",
) -> None:
    """Seed one item and, when ``branch`` is given, its worktree lane.

    ``repo_path`` is required alongside ``branch`` because the lane's
    recorded ``path`` is what every authority reader consumes; a lane
    row with a null path models no universe that worktree preparation
    can produce, and a fixture that omits it silently grants the
    session no authority at all.
    """
    insert_item(
        conn,
        id=item_id,
        project_id=project_id(project),
        status=status,
        workflow_id=workflow_id,
    )
    if branch:
        if repo_path is None:
            raise ValueError(
                "seed_item(branch=...) also needs repo_path: the lane's "
                "recorded path is the authority every reader consumes."
            )
        insert_item_worktree(
            conn,
            item_id=item_id,
            branch=branch,
            path=str(Path(repo_path) / ".worktrees" / branch),
            lane_role="integration" if workflow_id == "epic" else "implementation",
        )


def seed_epic_task(
    conn: Any,
    *,
    epic_id: int,
    task_num: int,
    branch: str,
    repo_path: "Any | None" = None,
) -> None:
    """Seed one epic task and its own worker lane.

    Carries ``repo_path`` for the same reason ``seed_item`` does: the
    lane's recorded path is the authority, and the task's claim
    resolves through ``epic_tasks.item_worktree_id`` to exactly this
    row.
    """
    if repo_path is None:
        raise ValueError(
            "seed_epic_task needs repo_path: the lane's recorded path "
            "is the authority every reader consumes."
        )
    insert_epic_task(
        conn,
        epic_id=epic_id,
        task_num=task_num,
        worktree=branch,
        worktree_path=str(Path(repo_path) / ".worktrees" / branch),
    )


def seed_item_claim(conn: Any, session_id: str, item_id: int) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claimed_at, last_heartbeat) "
        "VALUES (%s, 'item', %s, %s, %s)",
        (session_id, make_item_target(item_id).scope_json(), now, now),
    )
    conn.commit()


def seed_epic_task_claim(
    conn: Any,
    session_id: str,
    epic_id: int,
    task_num: int,
) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, "
        "claimed_at, last_heartbeat) "
        "VALUES (%s, 'epic_task', %s, %s, %s)",
        (session_id, make_epic_task_target(epic_id, task_num).scope_json(), now, now),
    )
    conn.commit()
