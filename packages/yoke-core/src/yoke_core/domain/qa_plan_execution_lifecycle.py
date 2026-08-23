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

_SETTLE_CAPTURE_FALLBACK_VERDICT = "error"
_SETTLE_CAPTURE_FALLBACK_REASON = (
    "execution ended without a review verdict; capture settled by "
    "execution termination"
)
_CAPTURE_RUNNERS = ("browser_substrate", "host_control", "agent_mission")


def _settle_unreviewed_capture_runs(conn: Any, execution: dict[str, Any]) -> None:
    """Settle still-unsettled capture runs for this execution's cases.

    A capture that never reached review (abort, error, or a case that ended
    blocked-on-precondition) would otherwise keep a NULL verdict and block
    every terminal transition forever. The execution's terminal state is the
    authoritative end of each capture's story, so the settlement names that
    honestly rather than attributing any reviewed quality signal.
    """
    requirement_ids = sorted(
        {
            int(case["requirement_id"])
            for case in execution.get("roster") or []
            if case.get("requirement_id") is not None
        }
    )
    if not requirement_ids:
        return
    placeholder = marker(conn)
    runners = ", ".join(placeholder for _ in _CAPTURE_RUNNERS)
    req_placeholders = ", ".join(placeholder for _ in requirement_ids)
    conn.execute(
        "UPDATE qa_runs SET verdict="
        f"{placeholder},verdict_reason={placeholder},"
        "completed_at=COALESCE(completed_at, "
        f"{placeholder}) "
        f"WHERE qa_requirement_id IN ({req_placeholders}) "
        f"AND performed_by IN ({runners}) "
        "AND verdict IS NULL",
        (
            _SETTLE_CAPTURE_FALLBACK_VERDICT,
            _SETTLE_CAPTURE_FALLBACK_REASON,
            iso8601_now(),
            *requirement_ids,
            *_CAPTURE_RUNNERS,
        ),
    )


_TERMINAL_EXECUTION_STATES = frozenset({"completed", "aborted", "error"})


def _mission_needs_retained_lease(execution: dict[str, Any]) -> bool:
    return any(
        case.get("runner_id") == "agent_mission"
        for case in execution.get("roster") or []
    )


def heartbeat_plan_execution(
    conn: Any,
    execution: dict[str, Any],
) -> None:
    """Refresh execution and held-machine liveness together."""
    if execution["state"] not in {"active", "awaiting_agent_review"}:
        raise QaPlanExecutionStateError("QA plan execution cannot heartbeat")
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
    commit: bool = True,
) -> None:
    """Finalize the execution, retaining a mission lease only for review."""
    if state not in {
        "completed",
        "aborted",
        "error",
        "waiting",
        "awaiting_agent_review",
    }:
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
    terminal_settlement = state in _TERMINAL_EXECUTION_STATES
    if terminal_settlement:
        _settle_unreviewed_capture_runs(conn, execution)
    retain_lease = (
        state == "awaiting_agent_review"
        and _mission_needs_retained_lease(execution)
    )
    if execution.get("machine_lease_id") is not None and not retain_lease:
        release_lease(
            conn,
            int(execution["machine_lease_id"]),
            reason,
            commit=commit,
        )
    placeholder = marker(conn)
    now = iso8601_now()
    completed_at = None if state in {"waiting", "awaiting_agent_review"} else now
    conn.execute(
        "UPDATE qa_plan_executions SET state="
        f"{placeholder},completed_at={placeholder},heartbeat_at={placeholder},"
        f"release_reason={placeholder},machine_lease_id={placeholder} "
        f"WHERE id={placeholder}",
        (
            state,
            completed_at,
            now,
            reason,
            execution.get("machine_lease_id") if retain_lease else None,
            str(execution["id"]),
        ),
    )
    if commit:
        conn.commit()
    execution["state"] = state
    if not retain_lease:
        execution["machine_lease_id"] = None
    execution["completed_at"] = completed_at
    execution["release_reason"] = reason


__all__ = [
    "finish_plan_execution",
    "heartbeat_plan_execution",
    "set_plan_machine_lease",
]
