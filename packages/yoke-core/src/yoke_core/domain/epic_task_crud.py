"""Task CRUD operations for epic tasks.

Owns ``task_upsert``, ``task_update_status``, ``task_update_body``, and
``task_update_field``. Re-exported from ``yoke_core.domain.epic`` for
patch-target compatibility so existing ``mock.patch("yoke_core.domain.epic.X")``
fixtures continue to intercept calls.

``task_update_status`` and ``task_update_body`` call into
``epic_task_sync.sync_task_label`` / ``sync_task_body`` via the parent-module
attribute lookup pattern (``import yoke_core.domain.epic as _epic_mod;
_epic_mod.epic_task_sync.sync_task_label(...)``) so existing test fixtures that
patch ``yoke_core.domain.epic.epic_task_sync.sync_task_label`` continue to
intercept calls regardless of which sibling module hosts the caller.
"""

from __future__ import annotations

import io
from typing import Optional

from yoke_core.domain.claim_chain_state import touch_epic_task_activity
from yoke_core.domain.epic_parsing import (
    TASK_FIELD_WHITELIST,
    _placeholder,
    _require_task_exists,
)
from yoke_core.domain.item_activity import touch_item_activity
from yoke_core.domain.item_status_transitions import record_task_transition
from yoke_core.domain.lifecycle import (
    ALL_TASK_STATUSES,
    TASK_TERMINAL_SUCCESS,
    is_valid_task_status,
)


def task_upsert(
    conn,
    epic_id: str,
    task_num: int,
    title: str,
    worktree: str = "",
    context_estimate: str = "",
    dependencies: str = "",
) -> str:
    """Upsert an epic task row (preserves existing fields on conflict)."""
    if not title:
        raise ValueError("title is required")
    if len(title) > 100:
        raise ValueError(
            f"epic task title exceeds 100 characters ({len(title)}). "
            "Shorten it or move details to the body."
        )
    p = _placeholder(conn)
    conn.execute(
        f"""INSERT INTO epic_tasks
           (epic_id, task_num, title, worktree, context_estimate, dependencies, status)
           VALUES ({p}, {p}, {p}, {p}, {p}, {p}, 'planning')
           ON CONFLICT(epic_id, task_num) DO UPDATE SET
             title=excluded.title,
             worktree=CASE WHEN excluded.worktree = '' OR excluded.worktree IS NULL
                           THEN epic_tasks.worktree
                           ELSE excluded.worktree END,
             context_estimate=excluded.context_estimate,
             dependencies=excluded.dependencies""",
        (str(epic_id), task_num, title, worktree, context_estimate, dependencies),
    )
    touch_item_activity(conn, item_id=epic_id)
    touch_epic_task_activity(conn, epic_id=epic_id, task_num=task_num)
    conn.commit()
    return f"Upserted task {epic_id}/{task_num}: {title}"


def task_update_status(
    conn,
    epic_id: str,
    task_num: int,
    status: str,
    *,
    pipeline: bool = False,
    qa_gate_bypass: bool = False,
    force: bool = False,
    scripts_dir: Optional[str] = None,
) -> str:
    """Update the status field of a task.

    Validates against the lifecycle task status set. Terminal success
    statuses are blocked unless *pipeline* is True (set by the status
    pipeline, ``yoke_core.domain.update_status``).
    """
    if not is_valid_task_status(status):
        raise ValueError(
            f"invalid epic task status {status} -- valid values: "
            + ",".join(sorted(ALL_TASK_STATUSES))
        )

    # Guard terminal success statuses
    if status in TASK_TERMINAL_SUCCESS and not pipeline:
        raise PermissionError(
            f"terminal status '{status}' cannot be set directly; it is "
            "pipeline-owned. Route through the status pipeline "
            "(python3 -m yoke_core.domain.update_status) so gates and "
            "cascades fire."
        )

    _require_task_exists(conn, epic_id, task_num)

    p = _placeholder(conn)
    old_row = conn.execute(
        f"SELECT status FROM epic_tasks WHERE epic_id={p} AND task_num={p}",
        (str(epic_id), task_num),
    ).fetchone()
    old_status = str(old_row[0]) if old_row is not None and old_row[0] else None
    conn.execute(
        f"UPDATE epic_tasks SET status={p} WHERE epic_id={p} AND task_num={p}",
        (status, str(epic_id), task_num),
    )
    # The pipeline caller (yoke_core.domain.update_status) records its own
    # transition row with the YOKE_STATUS_SOURCE attribution; recording
    # here too would double-count one mutation.
    if not pipeline and old_status != status:
        record_task_transition(
            conn,
            epic_id=epic_id,
            task_num=task_num,
            from_status=old_status,
            to_status=status,
            source="task-update-status",
        )
    conn.commit()
    if not pipeline:
        # Parent-module attribute lookup so patches on
        # ``yoke_core.domain.epic.epic_task_sync.sync_task_label`` intercept.
        import yoke_core.domain.epic as _epic_mod
        _epic_mod.epic_task_sync.sync_task_label(
            str(epic_id),
            task_num,
            status,
            conn=conn,
            stderr=io.StringIO(),
        )
    return f"Updated status of {epic_id}/{task_num} to {status}"


def task_update_body(
    conn,
    epic_id: str,
    task_num: int,
    body: str,
    *,
    scripts_dir: Optional[str] = None,
) -> str:
    """Update task body text."""
    p = _placeholder(conn)
    cur = conn.execute(
        f"UPDATE epic_tasks SET body={p} WHERE epic_id={p} AND task_num={p}",
        (body, str(epic_id), task_num),
    )
    if cur.rowcount == 0:
        raise LookupError(f"task '{epic_id}/{task_num}' not found")
    touch_item_activity(conn, item_id=epic_id)
    touch_epic_task_activity(conn, epic_id=epic_id, task_num=task_num)
    conn.commit()
    # Parent-module attribute lookup so patches on
    # ``yoke_core.domain.epic.epic_task_sync.sync_task_body`` intercept.
    import yoke_core.domain.epic as _epic_mod
    _epic_mod.epic_task_sync.sync_task_body(
        str(epic_id),
        task_num,
        conn=conn,
        stdout=io.StringIO(),
    )
    return f"Updated body of {epic_id}/{task_num}"


def task_update_field(
    conn,
    epic_id: str,
    task_num: int,
    field: str,
    value: str,
    **kwargs,
) -> str:
    """Update a single field on a task."""
    if field not in TASK_FIELD_WHITELIST:
        raise ValueError(f"invalid field '{field}' for task-update-field")

    # Delegate status updates to task_update_status for validation
    if field == "status":
        return task_update_status(conn, epic_id, task_num, value, **kwargs)

    _require_task_exists(conn, epic_id, task_num)
    p = _placeholder(conn)
    conn.execute(
        f"UPDATE epic_tasks SET {field}={p} WHERE epic_id={p} AND task_num={p}",
        (value, str(epic_id), task_num),
    )
    touch_item_activity(conn, item_id=epic_id)
    touch_epic_task_activity(conn, epic_id=epic_id, task_num=task_num)
    conn.commit()
    return f"Updated {field} of {epic_id}/{task_num} to {value}"
