"""Seeders for merge-audit tests against the production schema.

The merge-audit report tests (``test_merge_audit.py``,
``test_merge_audit_full.py``, ``test_merge_audit_full_extras.py``) seed items,
universal lanes, epic tasks and integration simulations through these helpers.
Simulations are recorded where the product reads them: ``qa_kind='simulation'``
QA requirements and runs.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.item_worktrees import (
    record_item_worktree,
    release_item_worktrees,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)

SIMULATION_VERDICTS = {"CLEAN": "pass", "GAPS FOUND": "fail"}


def seed_merge_audit_item(conn: Any, *, item_id: int, title: str, status: str) -> None:
    """Seed one Yoke-project item whose public ref is ``YOK-<item_id>``."""
    insert_item(conn, id=item_id, title=title, status=status, project="yoke")


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


def complete_merge_audit_item(conn: Any, *, item_id: int) -> None:
    """Mark an item done after its lanes are seeded; done items refuse new lanes."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(f"UPDATE items SET status = 'done' WHERE id = {marker}", (item_id,))


def seed_merge_audit_simulation(conn: Any, *, epic_id: int, result: str) -> None:
    """Record one integration simulation attempt in the canonical QA store."""
    requirement = insert_qa_requirement(
        conn,
        item_id=epic_id,
        qa_kind="simulation",
        success_policy=json.dumps(
            {"type": "deterministic", "criteria": "result_pass", "phase": "integration"}
        ),
    )
    insert_qa_run(
        conn,
        qa_requirement_id=requirement["id"],
        performed_by="agent",
        qa_kind="simulation",
        verdict=SIMULATION_VERDICTS[result],
        raw_result=json.dumps(
            {
                "body": f"SIMULATION: {result}\nEPIC: {render_item_ref(conn, epic_id)}",
                "phase": "integration",
            }
        ),
    )


__all__ = [
    "complete_merge_audit_item",
    "seed_merge_audit_item",
    "seed_merge_audit_lane",
    "seed_merge_audit_simulation",
    "seed_merge_audit_task",
]
