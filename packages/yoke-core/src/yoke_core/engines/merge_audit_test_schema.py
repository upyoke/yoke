"""Shared minimal-schema ``apply_schema`` strategy for merge-audit tests.

The merge-audit report tests (``test_merge_audit.py``,
``test_merge_audit_full.py``, ``test_merge_audit_full_extras.py``) all create a
small DB with the three tables ``merge_audit.generate_report`` reads:
``items``, ``item_worktrees``, ``epic_tasks``, and ``epic_simulations``. Because
``generate_report`` connects through the backend factory, the schema and seed
must land in the same Postgres authority as the read. This module owns the one
DDL definition and the zero-arg ``apply_schema`` strategy those fixtures hand to
``file_test_db.init_test_db`` plus the shared task-lane seeder, so neither the
DDL nor universal lane-linking setup is duplicated across the three test files.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.item_worktrees import (
    record_item_worktree,
    release_item_worktrees,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

MERGE_AUDIT_SCHEMA_DDL = """\
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'idea'
);
CREATE TABLE IF NOT EXISTS item_worktrees (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    branch TEXT NOT NULL,
    path TEXT,
    commit_sha TEXT,
    lane_role TEXT NOT NULL
      CHECK(lane_role IN ('implementation','worker','integration')),
    state TEXT NOT NULL DEFAULT 'active'
      CHECK(state IN ('active','released')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    released_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_item_worktrees_item_state
  ON item_worktrees(item_id, state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_item_worktrees_active_item_branch
  ON item_worktrees(item_id, branch)
  WHERE state = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS idx_item_worktrees_active_path
  ON item_worktrees(path)
  WHERE state = 'active' AND path IS NOT NULL AND path <> '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_item_worktrees_active_single_lane
  ON item_worktrees(item_id, lane_role)
  WHERE state = 'active'
    AND lane_role IN ('implementation', 'integration');
CREATE TABLE IF NOT EXISTS epic_tasks (
    epic_id INTEGER NOT NULL,
    task_num INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned',
    item_worktree_id INTEGER,
    PRIMARY KEY (epic_id, task_num)
);
CREATE TABLE IF NOT EXISTS epic_simulations (
    id INTEGER PRIMARY KEY,
    epic_id INTEGER NOT NULL,
    phase TEXT NOT NULL,
    result TEXT,
    created_at TEXT
);
"""


def seed_merge_audit_lane(
    conn: Any,
    *,
    item_id: int,
    branch: str,
    lane_role: str,
    state: str = "active",
) -> int:
    """Seed a universal lane, retaining released history when requested."""
    if state not in {"active", "released"}:
        raise ValueError(f"unsupported merge-audit lane state {state!r}")
    lane = record_item_worktree(
        conn,
        item_id=item_id,
        branch=branch,
        path=None,
        lane_role=lane_role,
        validate_policy=False,
    )
    if state == "released":
        release_item_worktrees(conn, item_id=item_id, branch=branch)
    return int(lane["id"])


def seed_merge_audit_task(
    conn: Any,
    *,
    epic_id: int,
    task_num: int,
    title: str,
    status: str,
    branch: str,
) -> int:
    """Seed an epic task linked to its active universal worker lane."""
    lane_id = seed_merge_audit_lane(
        conn,
        item_id=epic_id,
        branch=branch,
        lane_role="worker",
    )
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "INSERT INTO epic_tasks "
        "(epic_id, task_num, title, status, item_worktree_id) "
        f"VALUES ({', '.join(marker for _ in range(5))})",
        (epic_id, task_num, title, status, lane_id),
    )
    return lane_id


def apply_merge_audit_schema() -> None:
    """``apply_schema`` strategy applying :data:`MERGE_AUDIT_SCHEMA_DDL`.

    Resolves its connection through the backend factory, satisfying
    :func:`runtime.api.fixtures.file_test_db.init_test_db`'s zero-arg
    ``apply_schema`` contract. Merge-audit tests exercise the Postgres-backed
    authority directly.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, MERGE_AUDIT_SCHEMA_DDL)
    finally:
        conn.close()


__all__ = [
    "MERGE_AUDIT_SCHEMA_DDL",
    "apply_merge_audit_schema",
    "seed_merge_audit_lane",
    "seed_merge_audit_task",
]
