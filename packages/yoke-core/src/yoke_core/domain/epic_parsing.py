"""Epic parsing and input validation helpers.

Extracted from ``epic.py`` to keep the parent module focused on
orchestration, mutations, and the CLI surface.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_scalar


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TASK_COLUMNS = [
    "id", "epic_id", "task_num", "title", "worktree",
    "context_estimate", "dependencies", "status", "dispatch_attempts",
]

DISPATCH_CHAIN_COLUMNS = [
    "id", "epic_id", "worktree", "worktree_path", "queue",
    "current_index", "current_task", "current_attempt", "max_attempts",
    "no_chain", "started_at", "last_updated",
]

TASK_FIELD_WHITELIST = frozenset({
    "title", "worktree", "context_estimate", "dependencies", "status",
    "dispatch_attempts", "body", "github_issue", "branch", "worktree_path",
    "blocked_by", "max_attempts", "agent_id", "last_heartbeat",
})

CHAIN_FIELD_WHITELIST = frozenset({
    "worktree_path", "queue", "current_index", "current_task",
    "current_attempt", "max_attempts", "no_chain", "started_at",
    "last_updated",
})


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        parts.append("" if val is None else str(val))
    return "|".join(parts)


def _pipe_rows(rows, columns: List[str]) -> str:
    """Format multiple rows as pipe-delimited text (one line per row)."""
    return "\n".join(_pipe_row(r, columns) for r in rows)


# ---------------------------------------------------------------------------
# Epic ID parsing and validation
# ---------------------------------------------------------------------------

def _parse_epic_id(ref: str) -> str:
    """Parse an epic reference (YOK-N or bare int) to an ID string.

    Only accepts numeric epic IDs (with optional YOK- prefix).
    """
    if not ref:
        raise ValueError("epic ID is required")
    # Strip YOK- prefix (case-insensitive)
    eid = re.sub(r"^[Yy][Oo][Kk]-", "", ref).lstrip("0") or "0"
    if not eid.isdigit():
        raise ValueError(
            f"invalid epic ID '{ref}': only numeric IDs are accepted"
        )
    return eid


def _validate_epic_exists(conn, epic_id: str) -> None:
    """Validate that an epic ID exists in epic_tasks.

    Pure integers are assumed valid (lightweight check skipped);
    any non-digit string is rejected outright.
    """
    if epic_id.isdigit():
        return
    # ``epic_id`` is an INTEGER column; comparing it to a non-numeric slug raises
    # a type error on Postgres. Cast to TEXT so the doomed comparison yields zero
    # rows on both backends rather than aborting the transaction.
    count = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM epic_tasks WHERE CAST(epic_id AS TEXT)={_placeholder(conn)}",
        (epic_id,),
    )
    if count == 0:
        raise LookupError(
            f"epic '{epic_id}' not found in epic_tasks table (possible hallucinated slug)"
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
    """Parse simulation result from body text.

    Returns 'CLEAN', 'GAPS FOUND', or None.
    Matches the shell parse_result() logic exactly.
    """
    if not body:
        return None

    # Primary: match "SIMULATION: CLEAN" or "SIMULATION: GAPS FOUND"
    for line in body.splitlines():
        stripped = line.strip()
        m_sim = re.match(r"^SIMULATION:\s*(.+)$", stripped)
        if m_sim:
            val_sim = m_sim.group(1).strip().upper()
            if val_sim.startswith("CLEAN"):
                return "CLEAN"
            if val_sim.startswith("GAPS FOUND"):
                return "GAPS FOUND"

    # Fallback: match "## Result:" or "**Result:**"
    for line in body.splitlines():
        stripped = line.strip()

        m = re.match(r"^##\s+Result:\s*(.+)$", stripped)
        if m:
            val = m.group(1).strip()
            if val.upper().startswith("CLEAN"):
                return "CLEAN"
            if val.upper().startswith("GAPS FOUND"):
                return "GAPS FOUND"
            cm = re.match(r"^(\d+)\s+critical", val)
            if cm:
                counts = [int(x) for x in re.findall(r"(\d+)\s+(?:critical|warning|note)", val)]
                return "GAPS FOUND" if any(c > 0 for c in counts) else "CLEAN"
            return None

        m2 = re.match(r"^\*\*Result:\*\*\s*(.+)$", stripped)
        if m2:
            val2 = m2.group(1).strip()
            if "gap" in val2.lower() and re.search(r"[1-9]", val2):
                return "GAPS FOUND"
            if val2.upper().startswith("CLEAN"):
                return "CLEAN"
            if val2.upper().startswith("GAPS FOUND"):
                return "GAPS FOUND"
            return None

    return None
