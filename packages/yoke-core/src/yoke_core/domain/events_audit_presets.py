"""Failure-shaped presets for ``events list``.

The events table is ~99% hook telemetry; finding the rows that
represent a real failure across ``event_outcome`` ('failed', 'denied',
'interrupted', 'timeout') forces every audit pass to author its own
multi-filter SQL. These presets compose with the existing
``_build_where`` predicates so an operator can write
``events list --failed-only --session <id> --since "1 day ago"`` and
get the AND of every clause.

Two presets live here:

* ``--failed-only`` (``cmd_failed_only_list``) — list events whose
  ``event_outcome`` is in the failed-class set.
* ``--friction-summary`` (``cmd_friction_summary``) — group-by-session
  aggregation with one row per ``session_id`` and the per-outcome counts.

Both helpers own the full SQL execution; the CLI dispatcher only
forwards the pre-built WHERE / params from ``_build_where``.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.events_select import _EVT_SELECT_COLS, _format_rows


# Closed set of failure outcomes the ``--failed-only`` preset matches.
# Add new outcomes here if the events ledger grows new failure shapes;
# the column itself is enum-validated downstream.
FAILED_OUTCOMES: Tuple[str, ...] = (
    "failed",
    "denied",
    "interrupted",
    "timeout",
)


def _compose_failed_clause(
    where: str, params: Sequence[Any]
) -> Tuple[str, List[Any]]:
    placeholders = ",".join("%s" for _ in FAILED_OUTCOMES)
    clause = f"event_outcome IN ({placeholders})"
    bound = list(params) + list(FAILED_OUTCOMES)
    if where:
        return f"{where} AND {clause}", bound
    return f"WHERE {clause}", bound


def cmd_failed_only_list(
    db_path: Optional[str], where: str, params: Sequence[Any]
) -> str:
    """List events narrowed to the failed-class outcomes."""
    composed, bound = _compose_failed_clause(where, params)
    conn = connect(db_path)
    try:
        rows = query_rows(
            conn,
            f"SELECT {_EVT_SELECT_COLS} FROM events {composed} "
            "ORDER BY created_at ASC, id ASC",
            tuple(bound),
        )
        return _format_rows(rows)
    finally:
        conn.close()


def cmd_friction_summary(
    db_path: Optional[str], where: str, params: Sequence[Any]
) -> str:
    """Aggregate failed-class outcomes by ``session_id``.

    Returns one row per session_id with the failure counts, formatted
    as ``session_id|failed|denied|interrupted|timeout|total``. A header
    line precedes the rows so the output is self-describing for an
    operator scanning the terminal.
    """
    composed, bound = _compose_failed_clause(where, params)
    sql = (
        "SELECT session_id, event_outcome, COUNT(*) AS n FROM events "
        f"{composed} GROUP BY session_id, event_outcome "
        "ORDER BY session_id"
    )
    conn = connect(db_path)
    try:
        rows = query_rows(conn, sql, tuple(bound))
    finally:
        conn.close()

    per_session: dict[str, dict[str, int]] = {}
    for row in rows:
        sid = row["session_id"] or "(null)"
        per_session.setdefault(sid, {o: 0 for o in FAILED_OUTCOMES})
        per_session[sid][row["event_outcome"]] = int(row["n"])

    header_cols = ("session_id",) + FAILED_OUTCOMES + ("total",)
    out_lines: List[str] = ["|".join(header_cols)]
    for sid in sorted(per_session):
        counts = per_session[sid]
        total = sum(counts.values())
        values = [sid] + [str(counts[o]) for o in FAILED_OUTCOMES] + [str(total)]
        out_lines.append("|".join(values))
    return "\n".join(out_lines)


__all__ = [
    "FAILED_OUTCOMES",
    "cmd_failed_only_list",
    "cmd_friction_summary",
]
