"""Epic domain logic (invoked via ``python3 -m yoke_core.domain.epic``).

Manages epic task data: CRUD for ``epic_tasks``, ``epic_task_files``,
``epic_dispatch_chains``, ``epic_progress_notes``, plus QA-backed
review/simulation and cascade helpers.

Implementations live in sibling modules and are re-exported here so existing
callers and ``mock.patch("yoke_core.domain.epic.X")`` fixtures continue to
intercept calls:

* ``epic_task_crud`` — task CRUD: ``task_upsert``, ``task_update_status``,
  ``task_update_body``, ``task_update_field``.
* ``epic_dispatch`` — dispatch-chain CRUD/advance: ``dispatch_chain_upsert``,
  ``dispatch_chain_update``, ``dispatch_chain_advance``,
  ``dispatch_chain_refresh_for_activation``.
* ``epic_cascade`` — parent-status cascade: ``_CASCADE_MAP``,
  ``_resolve_session_id``, ``_cascade_project``, ``_emit_task_status_changed``,
  ``cascade_task_status``.
* ``epic_review`` — review/progress-notes/simulation/proceed-triage (lazy
  wrappers below).
* ``epic_resolution`` — read helpers (``task_get``, ``task_list``, etc.).
* ``epic_parsing`` — column lists, validation, and parse helpers.

CLI usage::

    python3 -m yoke_core.domain.epic <subcmd> [args...]

All output uses pipe-delimited format matching the CLI contract.
Exit codes: 0 success, 1 error/not-found, 2 usage error.
"""

from __future__ import annotations

import contextlib
import io
import select
import sys
from typing import List, Optional

# ---------------------------------------------------------------------------
# Re-exports from child modules (backward compatibility)
# ---------------------------------------------------------------------------
from yoke_core.domain.epic_parsing import (  # noqa: F401
    CHAIN_FIELD_WHITELIST,
    DISPATCH_CHAIN_COLUMNS,
    TASK_COLUMNS,
    TASK_FIELD_WHITELIST,
    _now_iso,
    _placeholder,
    _parse_epic_id,
    _parse_simulation_result,
    _pipe_row,
    _pipe_rows,
    _require_task_exists,
    _validate_epic_exists,
)
from yoke_core.domain.epic_resolution import (  # noqa: F401
    dispatch_chain_get,
    dispatch_chain_list,
    file_list,
    orphan_check,
    progress_note_list,
    progress_note_list_unsynced,
    review_get,
    review_list,
    simulation_get,
    task_get,
    task_get_body,
    task_list,
)
from yoke_core.domain.epic_submission_receipt import (  # noqa: F401
    extract_submission_block,
    parse_submission_fields,
    submission_receipt_get,
    validate_submission_fields,
)
from yoke_core.domain.epic_task_crud import (  # noqa: F401
    task_update_body,
    task_update_field,
    task_update_status,
    task_upsert,
)
from yoke_core.domain.epic_dispatch import (  # noqa: F401
    dispatch_chain_advance,
    dispatch_chain_refresh_for_activation,
    dispatch_chain_update,
    dispatch_chain_upsert,
)
from yoke_core.domain.epic_cascade import (  # noqa: F401
    _CASCADE_MAP,
    _cascade_project,
    _emit_task_status_changed,
    _resolve_session_id,
    cascade_task_status,
)

from yoke_core.domain.db_helpers import connect, query_one
from yoke_core.domain import epic_task_sync  # noqa: F401  -- patch target for sibling modules
from yoke_core.domain.qa import cmd_requirement_add, cmd_run_add


def _read_stdin_safe() -> str:
    """Read stdin without blocking when no data is available.

    Returns empty string if stdin is a tty, if stdin is closed/empty,
    or if no data is available (e.g., /dev/null redirection in tests).
    Only blocks when stdin is a pipe with data (the intended usage).
    """
    if sys.stdin.isatty():
        return ""
    # On Unix, use select to check if stdin has data
    if hasattr(select, "select"):
        readable, _, _ = select.select([sys.stdin], [], [], 0.1)
        if not readable:
            return ""
    return sys.stdin.read()


def _qa_requirement_add_silent(**kwargs) -> int:
    """Call the QA domain in-process without emitting its CLI stdout."""
    with contextlib.redirect_stdout(io.StringIO()):
        return cmd_requirement_add(**kwargs)


def _qa_run_add_silent(**kwargs) -> int:
    """Call the QA domain in-process without emitting its CLI stdout."""
    with contextlib.redirect_stdout(io.StringIO()):
        return cmd_run_add(**kwargs)


# ---------------------------------------------------------------------------
# Mutations: files
# ---------------------------------------------------------------------------

def file_add(
    conn,
    epic_id: str,
    task_num: int,
    file_path: str,
    action: str = "",
) -> str:
    """Add a file entry for a task."""
    # Explicit ON CONFLICT upsert preserves re-add semantics under native
    # Postgres while avoiding compatibility-era rewrite assumptions.
    p = _placeholder(conn)
    conn.execute(
        f"""INSERT INTO epic_task_files
           (epic_id, task_num, file_path, action)
           VALUES ({p}, {p}, {p}, {p})
           ON CONFLICT (epic_id, task_num, file_path)
           DO UPDATE SET action = excluded.action""",
        (str(epic_id), task_num, file_path, action),
    )
    conn.commit()
    return f"Added file {file_path} (action: {action}) to {epic_id}/{task_num}"


# ---------------------------------------------------------------------------
# Mutations: history / events
# ---------------------------------------------------------------------------

def history_insert(
    conn,
    epic_id: str,
    task_num: int,
    from_status: str,
    to_status: str,
    note: str = "",
    *,
    scripts_dir: Optional[str] = None,
) -> str:
    """Insert a status-change history row via the native Python emitter."""
    ctx = {"from_status": from_status, "to_status": to_status}
    if note:
        ctx["note"] = note

    del scripts_dir  # unused -- kept for API-compat; Python emitter resolves DB internally
    from yoke_core.domain.item_status_transitions import record_task_transition
    record_task_transition(
        conn,
        epic_id=epic_id,
        task_num=task_num,
        from_status=from_status,
        to_status=to_status,
        source="history-insert",
    )
    conn.commit()
    try:
        from yoke_core.domain.events import emit_event as _native_emit
        _native_emit(
            "TaskStatusChanged",
            event_kind="lifecycle",
            event_type="task_status_change",
            source_type="system",
            severity="STATUS",
            outcome="completed",
            item_id=f"YOK-{epic_id}",
            task_num=int(task_num),
            context=ctx,
        )
    except Exception:
        pass  # Non-fatal

    return f"Inserted history: {epic_id}/{task_num} {from_status} -> {to_status}"


# ---------------------------------------------------------------------------
# Review / progress-notes / simulation / proceed-triage
# (implementations live in epic_review.py — lazy wrappers keep epic.* patch targets)
# ---------------------------------------------------------------------------

def _ensure_implementation_review_requirement(conn, epic_id: str, task_num: int, *, scripts_dir: Optional[str] = None) -> int:
    from yoke_core.domain.epic_review import _ensure_implementation_review_requirement as _impl
    return _impl(conn, epic_id, task_num, scripts_dir=scripts_dir)


def review_seed(conn, epic_id: str, task_num: int, *, scripts_dir: Optional[str] = None) -> str:
    from yoke_core.domain.epic_review import review_seed as _impl
    return _impl(conn, epic_id, task_num, scripts_dir=scripts_dir)


def review_insert(conn, epic_id: str, task_num: int, verdict: str, body: str, *, scripts_dir: Optional[str] = None) -> str:
    from yoke_core.domain.epic_review import review_insert as _impl
    return _impl(conn, epic_id, task_num, verdict, body, scripts_dir=scripts_dir)


def progress_note_insert(conn, epic_id: str, task_num: int, note_num: int, body: str, commit_hash: str = "") -> str:
    from yoke_core.domain.epic_review import progress_note_insert as _impl
    return _impl(conn, epic_id, task_num, note_num, body, commit_hash)


def progress_note_mark_synced(conn, epic_id: str, task_num: int, note_num: int) -> str:
    from yoke_core.domain.epic_review import progress_note_mark_synced as _impl
    return _impl(conn, epic_id, task_num, note_num)


def simulation_upsert(conn, epic_id: str, phase: str, body: str, *, scripts_dir: Optional[str] = None) -> str:
    from yoke_core.domain.epic_review import simulation_upsert as _impl
    return _impl(conn, epic_id, phase, body, scripts_dir=scripts_dir)


def proceed_triage_and_handoff(
    epic_id: int,
    *,
    recommendation: str,
    gap_summary: str = "",
    filed_ticket_ids: Optional[List[str]] = None,
    session_id: Optional[str] = None,
) -> int:
    from yoke_core.domain.epic_review import proceed_triage_and_handoff as _impl
    return _impl(
        epic_id,
        recommendation=recommendation,
        gap_summary=gap_summary,
        filed_ticket_ids=filed_ticket_ids,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def _epic_task_files_has_unique(conn) -> bool:
    """Whether UNIQUE(epic_id, task_num, file_path) exists."""
    row = query_one(
        conn,
        """SELECT COUNT(*) AS cnt FROM information_schema.table_constraints
           WHERE table_name='epic_task_files' AND constraint_type='UNIQUE'""",
    )
    return bool(row and row["cnt"])


def _epic_task_files_rebuild_unique(conn) -> None:
    """Deduplicate then add the UNIQUE constraint."""
    conn.execute(
        "DELETE FROM epic_task_files WHERE id NOT IN "
        "(SELECT MIN(id) FROM epic_task_files GROUP BY epic_id, task_num, file_path)"
    )
    conn.execute(
        "ALTER TABLE epic_task_files ADD CONSTRAINT epic_task_files_unique "
        "UNIQUE (epic_id, task_num, file_path)"
    )
    conn.commit()


def migrate_task_files(conn) -> str:
    """Add UNIQUE constraint to epic_task_files (idempotent)."""
    if _epic_task_files_has_unique(conn):
        return "UNIQUE(epic_id, task_num, file_path) already in place -- no migration needed."

    before = query_one(conn, "SELECT COUNT(*) as cnt FROM epic_task_files")["cnt"]
    _epic_task_files_rebuild_unique(conn)
    after = query_one(conn, "SELECT COUNT(*) as cnt FROM epic_task_files")["cnt"]
    dropped = before - after

    lines = ["Migrating epic_task_files to add UNIQUE(epic_id, task_num, file_path)..."]
    if dropped > 0:
        lines.append(f"Dropped {dropped} duplicate rows during migration.")
    lines.append(f"Migration complete: {after} rows in epic_task_files (was {before}).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point (implementation lives in epic_cli.py)
# ---------------------------------------------------------------------------


def main(argv=None):
    """CLI entry point — delegates to epic_cli to avoid circular imports."""
    from yoke_core.domain.epic_cli import main as _cli_main
    return _cli_main(argv)


if __name__ == "__main__":
    main()
