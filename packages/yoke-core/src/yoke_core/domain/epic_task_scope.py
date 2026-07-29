"""Explicit generated-task repository scope and finalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists


SCOPE_PENDING = "pending"
SCOPE_PATHS = "paths"
SCOPE_NO_FILES = "no_files"
SCOPE_LEGACY_DEFERRED = "legacy_deferred"
SCOPE_STATES = (
    SCOPE_PENDING,
    SCOPE_PATHS,
    SCOPE_NO_FILES,
    SCOPE_LEGACY_DEFERRED,
)


class TaskScopeIncomplete(RuntimeError):
    """Generated tasks do not yet carry publishable explicit scope."""


@dataclass(frozen=True)
class TaskScopeRepairReport:
    tenant_id: str
    path_tasks: tuple[tuple[int, int], ...]
    deferred_tasks: tuple[tuple[int, int], ...]

    @property
    def diagnostics(self) -> tuple[str, ...]:
        return tuple(
            f"tenant={self.tenant_id} item=YOK-{item_id} "
            f"task={task_num} scope={state}"
            for state, pairs in (
                (SCOPE_PATHS, self.path_tasks),
                (SCOPE_LEGACY_DEFERRED, self.deferred_tasks),
            )
            for item_id, task_num in pairs
        )


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def schema_available(conn: Any) -> bool:
    return (
        _table_exists(conn, "epic_tasks")
        and _column_exists(conn, "epic_tasks", "scope_state")
        and _column_exists(conn, "epic_tasks", "scope_finalized_at")
    )


def lock_task_membership(conn: Any, item_id: int) -> None:
    """Serialize generated-task membership reads and writes for one item."""
    if not _table_exists(conn, "items"):
        return
    marker = _p(conn)
    cursor = conn.execute(
        f"UPDATE items SET id=id WHERE id={marker}",
        (int(item_id),),
    )
    if cursor.rowcount == 0:
        raise LookupError(f"YOK-{item_id} not found")


def ensure_new_task_membership_allowed(
    conn: Any,
    item_id: int,
    task_num: int,
) -> None:
    """Lock membership and reject inserts after whole-plan finalization."""
    if not schema_available(conn):
        return
    lock_task_membership(conn, int(item_id))
    marker = _p(conn)
    exists = conn.execute(
        "SELECT 1 FROM epic_tasks "
        f"WHERE epic_id={marker} AND task_num={marker}",
        (int(item_id), int(task_num)),
    ).fetchone()
    if exists is not None:
        return
    finalized = conn.execute(
        "SELECT 1 FROM epic_tasks "
        f"WHERE epic_id={marker} AND scope_finalized_at IS NOT NULL LIMIT 1",
        (int(item_id),),
    ).fetchone()
    if finalized is not None:
        raise TaskScopeIncomplete(
            f"YOK-{item_id} task membership is finalized; reopen task scope "
            f"before adding task {task_num}"
        )


def _rows(conn: Any, item_id: int | None = None) -> list[dict[str, Any]]:
    if not all(
        _table_exists(conn, table)
        for table in ("epic_tasks", "epic_task_files")
    ):
        return []
    marker = _p(conn)
    where = f"WHERE t.epic_id={marker} " if item_id is not None else ""
    params = (int(item_id),) if item_id is not None else ()
    state_expr = (
        "COALESCE(t.scope_state, 'pending')"
        if schema_available(conn)
        else "'pending'"
    )
    finalized_expr = (
        "t.scope_finalized_at" if schema_available(conn) else "NULL"
    )
    rows = conn.execute(
        "SELECT t.epic_id, t.task_num, "
        f"{state_expr} AS scope_state, "
        f"{finalized_expr} AS scope_finalized_at, "
        "COUNT(CASE WHEN TRIM(COALESCE(f.file_path, '')) <> '' "
        "THEN 1 END) AS file_count "
        "FROM epic_tasks t LEFT JOIN epic_task_files f "
        "ON f.epic_id=t.epic_id AND f.task_num=t.task_num "
        f"{where}"
        "GROUP BY t.epic_id, t.task_num, "
        f"{state_expr}, {finalized_expr} "
        "ORDER BY t.epic_id, t.task_num",
        params,
    ).fetchall()
    return [
        {
            "item_id": int(row["epic_id"] if hasattr(row, "keys") else row[0]),
            "task_num": int(row["task_num"] if hasattr(row, "keys") else row[1]),
            "state": str(
                row["scope_state"] if hasattr(row, "keys") else row[2]
            ),
            "finalized_at": (
                row["scope_finalized_at"] if hasattr(row, "keys") else row[3]
            ),
            "file_count": int(
                row["file_count"] if hasattr(row, "keys") else row[4]
            ),
        }
        for row in rows
    ]


def task_scope_issues(
    conn: Any,
    item_id: int,
    *,
    require_finalized: bool = True,
) -> list[str]:
    """Return deterministic task diagnostics without mutating scope."""
    issues: list[str] = []
    legacy_schema = not schema_available(conn)
    for row in _rows(conn, int(item_id)):
        label = f"YOK-{item_id} task {row['task_num']}"
        state = row["state"]
        count = row["file_count"]
        if legacy_schema:
            if count == 0:
                issues.append(f"{label} has no persisted file budget")
        elif state not in SCOPE_STATES:
            issues.append(f"{label} has invalid scope state {state!r}")
        elif state == SCOPE_PENDING:
            issues.append(f"{label} scope is pending")
        elif state == SCOPE_PATHS and count == 0:
            issues.append(f"{label} declares paths but has no file budget")
        elif state == SCOPE_NO_FILES and count:
            issues.append(f"{label} declares no_files but has {count} path(s)")
        elif state == SCOPE_LEGACY_DEFERRED:
            issues.append(f"{label} has deferred legacy scope")
        elif require_finalized and schema_available(conn) and not row["finalized_at"]:
            issues.append(f"{label} scope is not finalized")
    return issues


def set_no_files_scope(conn: Any, item_id: int, task_num: int) -> None:
    """Explicitly declare that one generated task touches no repository files."""
    if not schema_available(conn):
        raise TaskScopeIncomplete("epic task scope schema is unavailable")
    marker = _p(conn)
    has_paths = conn.execute(
        "SELECT 1 FROM epic_task_files "
        f"WHERE epic_id={marker} AND task_num={marker} "
        "AND TRIM(COALESCE(file_path, '')) <> '' LIMIT 1",
        (int(item_id), int(task_num)),
    ).fetchone()
    if has_paths is not None:
        raise TaskScopeIncomplete(
            f"YOK-{item_id} task {task_num} already has a file budget"
        )
    cursor = conn.execute(
        "UPDATE epic_tasks SET scope_state='no_files', "
        "scope_finalized_at=NULL "
        f"WHERE epic_id={marker} AND task_num={marker}",
        (int(item_id), int(task_num)),
    )
    if cursor.rowcount == 0:
        raise LookupError(f"YOK-{item_id} task {task_num} not found")
    conn.commit()


def finalize_generated_task_scopes(
    conn: Any,
    item_id: int,
    *,
    after_membership_read: Callable[[], None] | None = None,
) -> None:
    """Atomically finalize every task scope or leave every task unpublished."""
    if not schema_available(conn):
        issues = task_scope_issues(conn, int(item_id))
        if issues:
            raise TaskScopeIncomplete(
                f"YOK-{item_id} generated task scope cannot finalize: "
                + "; ".join(issues)
            )
        return
    marker = _p(conn)
    conn.execute("SAVEPOINT finalize_generated_task_scopes")
    try:
        lock_task_membership(conn, int(item_id))
        rows = _rows(conn, int(item_id))
        if not rows:
            conn.execute("RELEASE SAVEPOINT finalize_generated_task_scopes")
            conn.commit()
            return
        issues: list[str] = []
        for row in rows:
            state = row["state"]
            count = row["file_count"]
            if state == SCOPE_PENDING and count == 0:
                issues.append(f"task {row['task_num']} has no explicit scope")
            elif state == SCOPE_PATHS and count == 0:
                issues.append(f"task {row['task_num']} declares empty paths")
            elif state == SCOPE_NO_FILES and count:
                issues.append(
                    f"task {row['task_num']} declares no_files with paths"
                )
            elif state == SCOPE_LEGACY_DEFERRED:
                issues.append(
                    f"task {row['task_num']} has deferred legacy scope"
                )
            elif state not in SCOPE_STATES:
                issues.append(
                    f"task {row['task_num']} has invalid state {state!r}"
                )
        if issues:
            raise TaskScopeIncomplete(
                f"YOK-{item_id} generated task scope cannot finalize: "
                + "; ".join(issues)
            )
        if after_membership_read is not None:
            after_membership_read()
        conn.execute(
            "UPDATE epic_tasks SET scope_state='paths' "
            f"WHERE epic_id={marker} AND scope_state='pending' "
            "AND EXISTS (SELECT 1 FROM epic_task_files f "
            "WHERE f.epic_id=epic_tasks.epic_id "
            "AND f.task_num=epic_tasks.task_num "
            "AND TRIM(COALESCE(f.file_path, '')) <> '')",
            (int(item_id),),
        )
        conn.execute(
            "UPDATE epic_tasks SET scope_finalized_at=CURRENT_TIMESTAMP "
            f"WHERE epic_id={marker}",
            (int(item_id),),
        )
        conn.execute("RELEASE SAVEPOINT finalize_generated_task_scopes")
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT finalize_generated_task_scopes")
        conn.execute("RELEASE SAVEPOINT finalize_generated_task_scopes")
        raise


def repair_legacy_task_scopes(
    conn: Any,
    *,
    tenant_id: str | int = "current",
    item_id: int | None = None,
) -> TaskScopeRepairReport:
    """Idempotently type legacy task scope without guessing path ownership."""
    if not schema_available(conn):
        raise TaskScopeIncomplete("epic task scope schema is unavailable")
    marker = _p(conn)
    path_tasks: list[tuple[int, int]] = []
    deferred_tasks: list[tuple[int, int]] = []
    for row in _rows(conn, item_id):
        if row["state"] != SCOPE_PENDING:
            continue
        pair = (row["item_id"], row["task_num"])
        state = SCOPE_PATHS if row["file_count"] else SCOPE_LEGACY_DEFERRED
        (path_tasks if state == SCOPE_PATHS else deferred_tasks).append(pair)
        conn.execute(
            "UPDATE epic_tasks SET scope_state="
            f"{marker}, scope_finalized_at=CURRENT_TIMESTAMP "
            f"WHERE epic_id={marker} AND task_num={marker} "
            "AND scope_state='pending'",
            (state, *pair),
        )
    conn.commit()
    return TaskScopeRepairReport(
        tenant_id=str(tenant_id),
        path_tasks=tuple(path_tasks),
        deferred_tasks=tuple(deferred_tasks),
    )


__all__ = [
    "SCOPE_LEGACY_DEFERRED",
    "SCOPE_NO_FILES",
    "SCOPE_PATHS",
    "SCOPE_PENDING",
    "SCOPE_STATES",
    "TaskScopeIncomplete",
    "TaskScopeRepairReport",
    "finalize_generated_task_scopes",
    "ensure_new_task_membership_allowed",
    "lock_task_membership",
    "repair_legacy_task_scopes",
    "schema_available",
    "set_no_files_scope",
    "task_scope_issues",
]
