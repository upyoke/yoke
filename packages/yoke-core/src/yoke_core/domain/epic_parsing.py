"""Epic parsing and input validation helpers.

Extracted from ``epic.py`` to keep the parent module focused on
orchestration, mutations, and the CLI surface.
"""

from __future__ import annotations

from yoke_contracts.timestamps import format_instant
from typing import Any, List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.project_identity import render_item_ref


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TASK_COLUMNS = [
    "id",
    "epic_id",
    "task_num",
    "title",
    "item_worktree_id",
    "context_estimate",
    "dependencies",
    "status",
    "dispatch_attempts",
]

DISPATCH_CHAIN_COLUMNS = [
    "id",
    "epic_id",
    "item_worktree_id",
    "queue",
    "current_index",
    "current_task",
    "current_attempt",
    "max_attempts",
    "no_chain",
    "started_at",
    "last_updated",
]

TASK_FIELD_WHITELIST = frozenset(
    {
        "title",
        "item_worktree_id",
        "context_estimate",
        "dependencies",
        "status",
        "dispatch_attempts",
        "body",
        "github_issue",
        "max_attempts",
        "agent_id",
        "last_heartbeat",
    }
)

CHAIN_FIELD_WHITELIST = frozenset(
    {
        "queue",
        "current_index",
        "current_task",
        "current_attempt",
        "max_attempts",
        "no_chain",
        "started_at",
        "last_updated",
    }
)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# Pipe-delimited formatting
# ---------------------------------------------------------------------------


def _pipe_row(row, columns: List[str]) -> str:
    """Format a single sqlite3.Row as pipe-delimited text."""
    parts = []
    for col in columns:
        try:
            val = row[col]
        except (IndexError, KeyError):
            val = None
        if (
            col in ("started_at", "last_updated", "created_at", "last_heartbeat")
            and val is not None
        ):
            val = format_instant(val)
        parts.append("" if val is None else str(val))
    return "|".join(parts)


def _pipe_rows(rows, columns: List[str]) -> str:
    """Format multiple rows as pipe-delimited text (one line per row)."""
    return "\n".join(_pipe_row(r, columns) for r in rows)


# ---------------------------------------------------------------------------
# Epic ID parsing and validation
# ---------------------------------------------------------------------------


def _parse_epic_id(ref: str | int, *, conn: Any = None) -> int:
    """Resolve an epic command item argument through public identity."""
    from yoke_core.domain.yok_n_parser import parse_item_argument

    return parse_item_argument(ref, conn=conn)


def _validate_epic_exists(conn, epic_id: int) -> None:
    """Validate that a resolved internal epic id has task rows."""
    count = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM epic_tasks WHERE epic_id={_placeholder(conn)}",
        (epic_id,),
    )
    if count == 0:
        raise LookupError(
            f"epic {render_item_ref(conn, epic_id)} not found in epic_tasks table"
        )


def _require_task_exists(conn, epic_id: str, task_num: int) -> None:
    """Raise LookupError if the task does not exist."""
    count = query_scalar(
        conn,
        (
            "SELECT COUNT(*) FROM epic_tasks "
            f"WHERE epic_id={_placeholder(conn)} AND task_num={_placeholder(conn)}"
        ),
        (int(epic_id), task_num),
    )
    if count == 0:
        raise LookupError(f"task '{epic_id}/{task_num}' not found")


# ---------------------------------------------------------------------------
# Simulation result parsing
# ---------------------------------------------------------------------------


def _parse_simulation_result(body: str) -> str | None:
    """Return the canonical header verdict, or None for an invalid report."""
    from yoke_core.domain.simulation_report_headers import (
        SimulationReportError,
        parse_simulation_headers,
    )

    try:
        return parse_simulation_headers(body)
    except SimulationReportError:
        return None


def public_epic_pipe_rows(conn, epic_id: int, body: str) -> str:
    """Render the epic identity in the pipe rows exposed by registered reads."""
    public_ref = render_item_ref(conn, epic_id)
    rows = []
    for line in body.splitlines():
        fields = line.split("|")
        if len(fields) >= 2:
            fields[1] = public_ref
        rows.append("|".join(fields))
    return "\n".join(rows)
