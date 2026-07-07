"""Epic resolution logic -- read-only DB queries for epic records.

Extracted from ``epic.py`` to keep the parent module focused on
orchestration, mutations, and the CLI surface.
"""

from __future__ import annotations

from typing import List, Optional

from yoke_core.domain.db_helpers import query_one, query_rows, query_scalar
from yoke_core.domain.epic_parsing import (
    DISPATCH_CHAIN_COLUMNS,
    TASK_COLUMNS,
    _pipe_row,
    _pipe_rows,
    _require_task_exists,
)
from yoke_core.domain.sql_json import json_get, json_valid_expr


def _p(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# Task queries
# ---------------------------------------------------------------------------

def task_get(conn, epic_id: str, task_num: int) -> str:
    """Get one task row (pipe-delimited)."""
    row = query_one(
        conn,
        """SELECT id, epic_id, task_num, title, worktree,
                  context_estimate, dependencies, status, dispatch_attempts
           FROM epic_tasks WHERE epic_id={p} AND task_num={p}""".format(p=_p(conn)),
        (int(epic_id), task_num),
    )
    if row is None:
        raise LookupError(f"task '{epic_id}/{task_num}' not found")
    return _pipe_row(row, TASK_COLUMNS)


def task_list(conn, epic_id: str) -> str:
    """List all tasks for an epic (pipe-delimited, one per line)."""
    rows = query_rows(
        conn,
        """SELECT id, epic_id, task_num, title, worktree,
                  context_estimate, dependencies, status, dispatch_attempts
           FROM epic_tasks WHERE epic_id={p}
           ORDER BY task_num ASC""".format(p=_p(conn)),
        (int(epic_id),),
    )
    return _pipe_rows(rows, TASK_COLUMNS)


def task_get_body(conn, epic_id: str, task_num: int) -> str:
    """Get task body (outputs to stdout)."""
    _require_task_exists(conn, epic_id, task_num)
    val = query_scalar(
        conn,
        f"SELECT COALESCE(body, '') FROM epic_tasks "
        f"WHERE epic_id={_p(conn)} AND task_num={_p(conn)}",
        (int(epic_id), task_num),
    )
    return val if val is not None else ""


# ---------------------------------------------------------------------------
# File queries
# ---------------------------------------------------------------------------

def file_list(conn, epic_id: str, task_num: int) -> str:
    """List all files for a task (pipe-delimited)."""
    rows = query_rows(
        conn,
        """SELECT id, epic_id, task_num, file_path, action
           FROM epic_task_files WHERE epic_id={p} AND task_num={p}""".format(p=_p(conn)),
        (int(epic_id), task_num),
    )
    return _pipe_rows(rows, ["id", "epic_id", "task_num", "file_path", "action"])


# ---------------------------------------------------------------------------
# Dispatch chain queries
# ---------------------------------------------------------------------------

def dispatch_chain_get(conn, epic_id: str, worktree: str) -> str:
    """Get a dispatch chain row (pipe-delimited)."""
    row = query_one(
        conn,
        """SELECT id, epic_id, worktree,
                  COALESCE(worktree_path,'') as worktree_path,
                  COALESCE(queue,'') as queue,
                  current_index,
                  COALESCE(current_task,'') as current_task,
                  current_attempt, max_attempts,
                  no_chain,
                  COALESCE(started_at,'') as started_at,
                  COALESCE(last_updated,'') as last_updated
           FROM epic_dispatch_chains
           WHERE epic_id={p} AND worktree={p}""".format(p=_p(conn)),
        (int(epic_id), worktree),
    )
    if row is None:
        raise LookupError(f"dispatch chain '{epic_id}/{worktree}' not found")
    return _pipe_row(row, DISPATCH_CHAIN_COLUMNS)


def dispatch_chain_list(conn, epic_id: str) -> str:
    """List all dispatch chains for an epic (pipe-delimited)."""
    rows = query_rows(
        conn,
        """SELECT id, epic_id, worktree,
                  COALESCE(worktree_path,'') as worktree_path,
                  COALESCE(queue,'') as queue,
                  current_index,
                  COALESCE(current_task,'') as current_task,
                  current_attempt, max_attempts,
                  no_chain,
                  COALESCE(started_at,'') as started_at,
                  COALESCE(last_updated,'') as last_updated
           FROM epic_dispatch_chains
           WHERE epic_id={p}
           ORDER BY id ASC""".format(p=_p(conn)),
        (int(epic_id),),
    )
    return _pipe_rows(rows, DISPATCH_CHAIN_COLUMNS)


# ---------------------------------------------------------------------------
# Review queries
# ---------------------------------------------------------------------------

_REVIEW_COLUMNS = ["id", "epic_id", "task_num", "verdict", "body", "created_at"]


def _review_select_sql(conn) -> str:
    """Shared SELECT for review reads (newest first)."""
    return f"""SELECT qr.id,
                  qreq.epic_id,
                  qreq.task_num,
                  CASE qr.verdict WHEN 'pass' THEN 'PASS' WHEN 'fail' THEN 'FAIL' ELSE 'FAIL' END as verdict,
                  CASE WHEN {json_valid_expr('qr.raw_result')}
                       THEN COALESCE({json_get('qr.raw_result', '$.body')}, qr.raw_result)
                       ELSE COALESCE(qr.raw_result, '')
                  END as body,
                  qr.created_at
           FROM qa_runs qr
           JOIN qa_requirements qreq ON qr.qa_requirement_id = qreq.id
           WHERE qreq.qa_kind = 'implementation_review'
             AND qreq.epic_id = {_p(conn)}
             AND qreq.task_num = {_p(conn)}
             AND qreq.item_id IS NULL
           ORDER BY qr.created_at DESC, qr.id DESC"""


def review_get(conn, epic_id: str, task_num: int) -> str:
    """Get most recent review for a task (pipe-delimited).

    Format: id|epic_id|task_num|verdict|body|created_at
    """
    row = query_one(
        conn,
        _review_select_sql(conn) + " LIMIT 1",
        (int(epic_id), task_num),
    )
    if row is None:
        raise LookupError(f"no review found for '{epic_id}/{task_num}'")
    return _pipe_row(row, _REVIEW_COLUMNS)


def review_list(conn, epic_id: str, task_num: int, limit: int = 0) -> List[str]:
    """List review history for a task as pipe rows, newest first.

    Each entry uses the :func:`review_get` row format. Returns one
    string per review row (NOT pre-joined: review bodies are
    multi-line, so callers that need a row count must count entries,
    never text lines). ``limit`` of 0 means "no limit"; zero rows is
    an empty list, not an error (unlike ``review_get``).
    """
    sql = _review_select_sql(conn)
    params: tuple = (int(epic_id), task_num)
    if limit and limit > 0:
        sql += f" LIMIT {_p(conn)}"
        params = (int(epic_id), task_num, int(limit))
    rows = query_rows(conn, sql, params)
    return [_pipe_row(r, _REVIEW_COLUMNS) for r in rows]


# ---------------------------------------------------------------------------
# Progress note queries
# ---------------------------------------------------------------------------

def progress_note_list_unsynced(conn, epic_id: str) -> str:
    """List progress notes not yet synced to GitHub (pipe-delimited)."""
    rows = query_rows(
        conn,
        """SELECT id, epic_id, task_num, note_num,
                  COALESCE(body,'') as body,
                  COALESCE(commit_hash,'') as commit_hash,
                  synced_to_github, created_at
           FROM epic_progress_notes
           WHERE epic_id={p} AND synced_to_github=0
           ORDER BY task_num ASC, note_num ASC""".format(p=_p(conn)),
        (int(epic_id),),
    )
    cols = ["id", "epic_id", "task_num", "note_num", "body", "commit_hash",
            "synced_to_github", "created_at"]
    return _pipe_rows(rows, cols)


def progress_note_list(
    conn, epic_id: str, task_num: int, limit: int = 0,
) -> str:
    """List all progress notes for an (epic, task) pair, pipe-delimited.

    Generic counterpart to ``progress_note_list_unsynced`` — returns every
    note regardless of sync state. Ordered by ``note_num DESC`` so the
    most recent note prints first. ``limit`` of 0 means "no limit".
    """
    sql = """SELECT id, epic_id, task_num, note_num,
                    COALESCE(body,'') as body,
                    COALESCE(commit_hash,'') as commit_hash,
                    synced_to_github, created_at
             FROM epic_progress_notes
             WHERE epic_id={p} AND task_num={p}
             ORDER BY note_num DESC""".format(p=_p(conn))
    params: tuple = (int(epic_id), int(task_num))
    if limit and limit > 0:
        sql += f" LIMIT {_p(conn)}"
        params = (int(epic_id), int(task_num), int(limit))
    rows = query_rows(conn, sql, params)
    cols = ["id", "epic_id", "task_num", "note_num", "body", "commit_hash",
            "synced_to_github", "created_at"]
    return _pipe_rows(rows, cols)


# ---------------------------------------------------------------------------
# Simulation queries
# ---------------------------------------------------------------------------

def simulation_get(conn, epic_id: str, phase: str) -> str:
    """Get a simulation report (pipe-delimited).

    Format: id|epic_id|phase|result|body|created_at
    """
    row = query_one(
        conn,
        f"""SELECT qr.id,
                  qreq.item_id,
                  CASE WHEN substr(qr.raw_result, 1, 1) = '{{'
                       THEN COALESCE({json_get('qr.raw_result', '$.phase')}, '')
                       ELSE ''
                  END as phase,
                  CASE qr.verdict
                    WHEN 'pass' THEN 'CLEAN'
                    WHEN 'fail' THEN 'GAPS FOUND'
                    ELSE ''
                  END as result,
                  CASE WHEN substr(qr.raw_result, 1, 1) = '{{'
                       THEN COALESCE({json_get('qr.raw_result', '$.body')}, '')
                       ELSE qr.raw_result
                  END as body,
                  qr.created_at
           FROM qa_runs qr
           JOIN qa_requirements qreq ON qr.qa_requirement_id = qreq.id
           WHERE qreq.qa_kind = 'simulation'
             AND qreq.item_id = {_p(conn)}
             -- deliberate case-sensitive match against internal JSON-literal values
             AND qreq.success_policy LIKE {_p(conn)}
             AND substr(qr.raw_result, 1, 1) = '{{'
             -- deliberate case-sensitive match against internal JSON-literal values
             AND qr.raw_result LIKE {_p(conn)}
           ORDER BY qr.created_at DESC, qr.id DESC
           LIMIT 1""",
        (int(epic_id), f'%"phase":"{phase}"%', f'%"phase":"{phase}"%'),
    )
    if row is None:
        raise LookupError(f"simulation '{epic_id}/{phase}' not found")
    return _pipe_row(row, ["id", "item_id", "phase", "result", "body", "created_at"])


# ---------------------------------------------------------------------------
# Orphan check
# ---------------------------------------------------------------------------

def orphan_check(conn) -> str:
    """Find epics with tasks but no Technical Plan.

    Returns one YOK-N per line, or empty string.
    checks technical_plan structured field instead of retired body column.
    """
    rows = query_rows(
        conn,
        # ``et.epic_id`` is in the DISTINCT select list so the numeric ORDER BY
        # is valid on Postgres (SELECT DISTINCT requires ORDER BY exprs to appear
        # in the select list); the redundant ``item_ref`` is dropped at projection.
        """SELECT DISTINCT et.epic_id as epic_id, 'YOK-' || et.epic_id as item_ref
           FROM epic_tasks et
           JOIN items i ON i.id = et.epic_id
           WHERE i.type = 'epic'
             AND (i.technical_plan IS NULL OR TRIM(i.technical_plan) = '')
           ORDER BY et.epic_id ASC""",
    )
    return "\n".join(r["item_ref"] for r in rows)
