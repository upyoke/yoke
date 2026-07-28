"""Heartbeat, lease, and final-state writes for ordered QA execution."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.coordination_leases import heartbeat_lease, release_lease
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    marker,
)


_TERMINAL_EXECUTION_STATES = frozenset({"completed", "aborted", "error"})


def heartbeat_plan_execution(
    conn: Any,
    execution: dict[str, Any],
) -> None:
    """Refresh execution and held-machine liveness together."""
    if execution["state"] != "active":
        raise QaPlanExecutionStateError("QA plan execution is not active")
    placeholder = marker(conn)
    now = iso8601_now()
    conn.execute(
        "UPDATE qa_plan_executions SET heartbeat_at="
        f"{placeholder} WHERE id={placeholder}",
        (now, str(execution["id"])),
    )
    if execution.get("machine_lease_id") is not None:
        heartbeat_lease(conn, int(execution["machine_lease_id"]), now=now)
    else:
        conn.commit()
    execution["heartbeat_at"] = now


def set_plan_machine_lease(
    conn: Any,
    execution: dict[str, Any],
    *,
    lease_id: int,
) -> None:
    """Attach the server-acquired Test Mac lease to the durable plan."""
    placeholder = marker(conn)
    now = iso8601_now()
    cursor = conn.execute(
        "UPDATE qa_plan_executions SET machine_lease_id="
        f"{placeholder},heartbeat_at={placeholder} WHERE id={placeholder} "
        "AND state='active' AND machine_lease_id IS NULL",
        (int(lease_id), now, str(execution["id"])),
    )
    if cursor.rowcount != 1:
        conn.rollback()
        raise QaPlanExecutionStateError(
            "QA plan execution cannot attach the machine lease"
        )
    conn.commit()
    execution["machine_lease_id"] = int(lease_id)
    execution["heartbeat_at"] = now


def finish_plan_execution(
    conn: Any,
    execution: dict[str, Any],
    *,
    state: str,
    reason: str,
) -> None:
    """Finalize the execution and idempotently release its machine lease."""
    if state not in {"completed", "aborted", "error", "waiting"}:
        raise QaPlanExecutionStateError(f"invalid final execution state {state!r}")
    current_state = str(execution["state"])
    if current_state == state:
        return
    if current_state in _TERMINAL_EXECUTION_STATES:
        raise QaPlanExecutionStateError(
            "QA plan execution is already terminal as "
            f"{current_state!r}; transition to {state!r} refused"
        )
    if state == "completed" and int(execution["cursor_ordinal"]) != len(
        execution["roster"]
    ):
        raise QaPlanExecutionStateError(
            "QA plan execution cannot complete before every case advances"
        )
    if execution.get("machine_lease_id") is not None:
        release_lease(conn, int(execution["machine_lease_id"]), reason)
    placeholder = marker(conn)
    now = iso8601_now()
    completed_at = None if state == "waiting" else now
    conn.execute(
        "UPDATE qa_plan_executions SET state="
        f"{placeholder},completed_at={placeholder},heartbeat_at={placeholder},"
        f"release_reason={placeholder},machine_lease_id=NULL "
        f"WHERE id={placeholder}",
        (state, completed_at, now, reason, str(execution["id"])),
    )
    conn.commit()
    execution["state"] = state
    execution["machine_lease_id"] = None
    execution["completed_at"] = completed_at
    execution["release_reason"] = reason


__all__ = [
    "finish_plan_execution",
    "heartbeat_plan_execution",
    "set_plan_machine_lease",
]
