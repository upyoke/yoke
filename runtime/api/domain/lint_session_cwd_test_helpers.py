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

from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from yoke_core.domain.db_helpers import iso8601_now

_PROJECT_IDS = {"yoke": 1, "externalwebapp": 2}


def project_id(project: str = "yoke") -> int:
    return _PROJECT_IDS.get(project, 100)


def seed_item(
    conn: Any,
    *,
    item_id: int,
    branch: "str | None",
    project: str = "yoke",
    status: str = "implementing",
) -> None:
    insert_item(
        conn,
        id=item_id,
        worktree=branch,
        project_id=project_id(project),
        status=status,
    )


def seed_epic_task(
    conn: Any, *, epic_id: int, task_num: int, branch: str,
) -> None:
    insert_epic_task(
        conn, epic_id=epic_id, task_num=task_num, worktree=branch,
    )


def seed_item_claim(conn: Any, session_id: str, item_id: int) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claimed_at, last_heartbeat) "
        "VALUES (%s, 'item', %s, %s, %s)",
        (session_id, item_id, now, now),
    )
    conn.commit()


def seed_epic_task_claim(
    conn: Any, session_id: str, epic_id: int, task_num: int,
) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, epic_id, task_num, "
        "claimed_at, last_heartbeat) "
        "VALUES (%s, 'epic_task', %s, %s, %s, %s)",
        (session_id, epic_id, task_num, now, now),
    )
    conn.commit()
