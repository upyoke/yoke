"""Pending resume-notice state machine on ``harness_sessions``.

The slim "SESSION RESUMED" block renders exactly once per reactivation
cycle. The render-once state is the ``pending_resume_notice`` JSON
column: reactivation (:mod:`sessions_lifecycle_reactivation`) writes it,
the hook-runner render (:mod:`sessions_resume_block`) reads and clears
it. ``HarnessSessionResumeBlockShown`` remains a telemetry marker only —
no reader reconstructs this state from the events ledger.

Split from ``sessions_lifecycle_reactivation`` so the auto-reacquire
flow stays under the authored-file budget.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .schema_common import _get_columns as _schema_get_columns


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _column_present(conn: Any) -> bool:
    try:
        return "pending_resume_notice" in set(
            _schema_get_columns(conn, "harness_sessions")
        )
    except Exception:
        return False


def write_pending_resume_notice(
    conn: Any,
    session_id: str,
    *,
    released_claims: List[Dict[str, Any]],
    reacquired_count: int,
    conflict_count: int,
) -> bool:
    """Persist the pending slim-resume-block payload on the session row.

    Returns False (no write) when the schema predates the column — the
    minimal-fixture tolerance pattern shared with the activity columns.
    """
    if not _column_present(conn):
        return False
    notice = {
        "reactivated_at": _now_iso(),
        "released_claims": released_claims,
        "reacquired_count": int(reacquired_count),
        "conflict_count": int(conflict_count),
    }
    conn.execute(
        "UPDATE harness_sessions SET pending_resume_notice = %s "
        "WHERE session_id = %s",
        (json.dumps(notice, separators=(",", ":")), session_id),
    )
    conn.commit()
    return True


def lookup_unacknowledged_resume_block(
    conn: Any,
    session_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the pending slim-resume-block payload, or ``None``.

    ``None`` means the block already rendered or there is no
    reactivation to surface.
    """
    if not _column_present(conn):
        return None
    row = conn.execute(
        "SELECT pending_resume_notice FROM harness_sessions "
        "WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    raw = row[0] if not hasattr(row, "keys") else row["pending_resume_notice"]
    if not raw:
        return None
    try:
        notice = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return notice if isinstance(notice, dict) else None


def clear_pending_resume_notice(conn: Any, session_id: str) -> None:
    """Mark the slim resume block as rendered for this reactivation cycle."""
    conn.execute(
        "UPDATE harness_sessions SET pending_resume_notice = NULL "
        "WHERE session_id = %s",
        (session_id,),
    )
    conn.commit()


__all__ = [
    "clear_pending_resume_notice",
    "lookup_unacknowledged_resume_block",
    "write_pending_resume_notice",
]
