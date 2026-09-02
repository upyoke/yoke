"""Heartbeat, lease, and final-state writes for ordered QA execution."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.coordination_claims import heartbeat, release
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.qa_capture_settlement import (
    settle_unreviewed_execution_captures,
)
from yoke_core.domain.qa_execution_decision_disposition import (
    dispose_execution_decisions,
)
from yoke_core.domain.qa_plan_execution_authority import (
    PLAN_EXECUTION_STALE_SECONDS,
    plan_execution_is_abandoned,
)
from yoke_core.domain.qa_plan_execution_schema import (
    LIVE_PLAN_EXECUTION_SQL,
    TERMINAL_PLAN_EXECUTION_STATES,
)
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    lock_plan_execution,
    marker,
)
from yoke_core.domain.qa_plan_execution_target_snapshot import (
    require_execution_target,
)
from yoke_core.domain.schema_common import _table_exists


STALE_PLAN_EXECUTION_REASON = "stale-heartbeat"


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
    require_execution_target(execution)
    placeholder = marker(conn)
    now = iso8601_now()
    conn.execute(
        "UPDATE qa_plan_executions SET heartbeat_at="
        f"{placeholder} WHERE id={placeholder}",
        (now, str(execution["id"])),
    )
    if execution.get("machine_lease_id") is not None:
        heartbeat(conn, int(execution["machine_lease_id"]), now=now)
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
    if current_state in TERMINAL_PLAN_EXECUTION_STATES:
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
    terminal_settlement = state in TERMINAL_PLAN_EXECUTION_STATES
    if terminal_settlement:
        settle_unreviewed_execution_captures(conn, execution)
    retain_lease = state == "awaiting_agent_review" and _mission_needs_retained_lease(
        execution
    )
    if execution.get("machine_lease_id") is not None and not retain_lease:
        release(
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
    execution["state"] = state
    if not retain_lease:
        execution["machine_lease_id"] = None
    execution["completed_at"] = completed_at
    execution["release_reason"] = reason
    if terminal_settlement:
        dispose_execution_decisions(conn, execution, commit=False)
    if commit:
        conn.commit()


def reap_stale_plan_executions(
    conn: Any,
    *,
    now: Any | None = None,
) -> list[dict[str, Any]]:
    """Abandon every execution whose owner has stopped reporting progress.

    Without this, an execution whose owning session died stays live forever,
    and every human decision it raised waits on a termination that never
    arrives. Reaping is deliberately vintage-blind: it settles the row from
    its heartbeat alone, so the oldest strandings -- the ones with the least
    complete rows -- are exactly the ones it can still clear.

    Silence is not always absence, so the heartbeat is read beside the owning
    session's declared posture: a session parked on instruction is present
    and holding, and its execution is skipped. That test lives here rather
    than in a park-time heartbeat stamp because a stamped heartbeat would
    claim progress that is not happening -- and would go stale again minutes
    later anyway, while the walker is still legitimately holding.
    """
    if not _table_exists(conn, "qa_plan_executions"):
        return []
    candidates = [
        {"id": str(row[0]), "heartbeat_at": row[1], "session_id": row[2]}
        for row in conn.execute(
            "SELECT id, heartbeat_at, session_id FROM qa_plan_executions "
            f"WHERE state IN ({LIVE_PLAN_EXECUTION_SQL}) ORDER BY created_at, id"
        ).fetchall()
    ]
    reaped: list[dict[str, Any]] = []
    for candidate in candidates:
        if not plan_execution_is_abandoned(conn, candidate, now=now):
            continue
        try:
            execution = lock_plan_execution(conn, candidate["id"])
            if str(execution["state"]) in TERMINAL_PLAN_EXECUTION_STATES:
                conn.rollback()
                continue
            finish_plan_execution(
                conn,
                execution,
                state="aborted",
                reason=STALE_PLAN_EXECUTION_REASON,
            )
        except QaPlanExecutionStateError as exc:
            conn.rollback()
            reaped.append(
                {
                    "execution_id": candidate["id"],
                    "reaped": False,
                    "detail": str(exc),
                    "heartbeat_at": candidate["heartbeat_at"],
                }
            )
            continue
        reaped.append(
            {
                "execution_id": str(execution["id"]),
                "reaped": True,
                "state": str(execution["state"]),
                "release_reason": STALE_PLAN_EXECUTION_REASON,
                "heartbeat_at": candidate["heartbeat_at"],
            }
        )
    return reaped


__all__ = [
    "PLAN_EXECUTION_STALE_SECONDS",
    "STALE_PLAN_EXECUTION_REASON",
    "finish_plan_execution",
    "heartbeat_plan_execution",
    "reap_stale_plan_executions",
    "set_plan_machine_lease",
]
