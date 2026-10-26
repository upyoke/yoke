"""What a session's own rows say about ending its current turn.

The reads the Stop promised-work gate makes, kept beside each other
because they answer the same question from opposite directions: has this
session *declared* that going quiet is intended — by parking, or by
recording a CI wait that will wake it — and is it *holding* something
that going quiet would kill.

Both read the session's own rows rather than the telemetry ledger. The
two carry the same facts, but telemetry expires, and an expired row here
would not read as "nothing is armed" — it would read as permission to
end a turn that is holding a waiter with no wake behind it.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_mode import SESSION_MODE_PARKED


def session_parked(conn: Any, session_id: str) -> bool:
    """Whether *session_id* has stamped ``parked`` about itself.

    Parking is how a session declares that going quiet is the intended
    next state — a release wait, a steering seat between wakes. Holding
    such a Stop anyway is what turned one wait into a loop: blocked Stop,
    re-arm, blocked Stop again, with nothing the reinjected directive
    could accomplish. The park is the declaration; the session's own next
    tool call takes it back.
    """
    from yoke_core.domain import db_backend

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT mode FROM harness_sessions WHERE session_id={p}",
        (session_id,),
    ).fetchone()
    if row is None:
        return False
    return str(row["mode"] or "") == SESSION_MODE_PARKED


def ci_wait_pending(conn: Any, session_id: str) -> bool:
    """Whether *session_id* has a recorded CI wait not yet notified.

    Recording the wait is how a session hands its CI verdict to the wait
    observer and ends its turn: the verdict is pushed back when the run
    concludes. Holding that Stop would push a continuation before there
    is anything to continue with.
    """
    from yoke_core.domain import db_backend

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT 1 FROM session_ci_run_waits "
        f"WHERE session_id={p} AND notified_at IS NULL LIMIT 1",
        (session_id,),
    ).fetchone()
    return row is not None


def monitor_waiter_armed(conn: Any, session_id: str) -> bool:
    """Whether *session_id*'s last finished call was a ``Monitor`` arming.

    A Monitor wake resumes the current turn, so ending that turn closes
    the reader and the paired subscription dies with it — a clean-looking
    exit that produces no wake and no completion record.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.session_tool_call_projections import (
        LAST_COMPLETED_TOOL_COLUMN,
        MONITOR_TOOL_NAME,
        last_completed_tool_select,
    )

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT hs.session_id"
        f"{last_completed_tool_select(conn, session_alias='hs')} "
        f"FROM harness_sessions hs WHERE hs.session_id={p}",
        (session_id,),
    ).fetchone()
    if row is None:
        return False
    return str(row[LAST_COMPLETED_TOOL_COLUMN] or "") == MONITOR_TOOL_NAME


__all__ = ["ci_wait_pending", "monitor_waiter_armed", "session_parked"]
