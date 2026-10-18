"""Generated-task scope: membership locking, finalization and body checks.

A task's repository scope is its body's ``## Files Touched`` section
(:mod:`task_files_touched`). This module serializes membership changes,
finalizes the whole task set on the item (``items.
generated_task_membership_finalized_at``), and reports every task whose
section does not yet declare its files.
"""

from __future__ import annotations

from typing import Any, Callable

from yoke_core.domain import db_backend
from yoke_core.domain.epic_task_membership import (
    clear_membership_finalized,
    membership_is_finalized,
    stamp_membership_finalized,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.task_files_touched import (
    FILES_TOUCHED_RECIPE,
    item_task_files,
)


class TaskScopeIncomplete(RuntimeError):
    """Generated tasks do not yet carry publishable explicit scope."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def lock_task_membership(conn: Any, item_id: int) -> None:
    """Serialize generated-task membership reads and writes for one item."""
    marker = _p(conn)
    cursor = conn.execute(
        f"UPDATE items SET id=id WHERE id={marker}",
        (int(item_id),),
    )
    if cursor.rowcount == 0:
        raise LookupError(f"{render_item_ref(conn, int(item_id))} not found")


def ensure_new_task_membership_allowed(
    conn: Any,
    item_id: int,
    task_num: int,
) -> None:
    """Lock membership and reject inserts after whole-plan finalization."""
    lock_task_membership(conn, int(item_id))
    marker = _p(conn)
    exists = conn.execute(
        f"SELECT 1 FROM epic_tasks WHERE epic_id={marker} AND task_num={marker}",
        (int(item_id), int(task_num)),
    ).fetchone()
    if exists is not None:
        return
    if membership_is_finalized(conn, int(item_id)):
        raise TaskScopeIncomplete(
            f"{render_item_ref(conn, int(item_id))} task membership is finalized; "
            f"reopen task scope before adding task {task_num}"
        )


def reopen_generated_task_scopes(
    conn: Any,
    item_id: int,
    *,
    commit: bool = True,
) -> int:
    """Invalidate the finalized membership snapshot before amendment."""
    marker = _p(conn)
    if (
        conn.execute(
            f"SELECT 1 FROM items WHERE id={marker}", (int(item_id),)
        ).fetchone()
        is None
    ):
        return 0
    lock_task_membership(conn, int(item_id))
    changed = clear_membership_finalized(conn, int(item_id))
    if commit:
        conn.commit()
    return changed


def _section_issues(conn: Any, item_id: int) -> list[str]:
    public_ref = render_item_ref(conn, int(item_id))
    issues = [
        f"{public_ref} task {task_num} {files.problem()}"
        for task_num, files in item_task_files(conn, int(item_id)).items()
        if not files.declared
    ]
    if issues:
        issues.append(f"recovery: {FILES_TOUCHED_RECIPE}")
    return issues


def task_scope_issues(
    conn: Any,
    item_id: int,
    *,
    require_finalized: bool = True,
) -> list[str]:
    """Return deterministic task diagnostics without mutating scope."""
    issues = _section_issues(conn, int(item_id))
    if (
        require_finalized
        and not issues
        and item_task_files(conn, int(item_id))
        and not membership_is_finalized(conn, int(item_id))
    ):
        issues.append(
            f"{render_item_ref(conn, int(item_id))} task membership is not "
            "finalized; recovery: `yoke workflow-item epic-task scope-finalize`"
        )
    return issues


def finalize_generated_task_scopes(
    conn: Any,
    item_id: int,
    *,
    after_membership_read: Callable[[], None] | None = None,
) -> None:
    """Finalize the task set only when every task declares its files."""
    public_ref = render_item_ref(conn, int(item_id))
    conn.execute("SAVEPOINT finalize_generated_task_scopes")
    try:
        lock_task_membership(conn, int(item_id))
        issues = _section_issues(conn, int(item_id))
        if issues:
            raise TaskScopeIncomplete(
                f"{public_ref} generated task scope cannot finalize: "
                + "; ".join(issues)
            )
        if after_membership_read is not None:
            after_membership_read()
        if not stamp_membership_finalized(conn, int(item_id)):
            raise TaskScopeIncomplete(
                f"{public_ref} task membership snapshot could not be finalized"
            )
        conn.execute("RELEASE SAVEPOINT finalize_generated_task_scopes")
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT finalize_generated_task_scopes")
        conn.execute("RELEASE SAVEPOINT finalize_generated_task_scopes")
        raise


__all__ = [
    "TaskScopeIncomplete",
    "finalize_generated_task_scopes",
    "ensure_new_task_membership_allowed",
    "lock_task_membership",
    "reopen_generated_task_scopes",
    "task_scope_issues",
]
