"""Heartbeat, lease, and final-state writes for ordered QA execution."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.coordination_claims import heartbeat, release
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.qa_capture_settlement import (
    record_inflight_case_failure,
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
    from yoke_core.domain.qa_plan_execution_abort_state import abort_request

    if execution["state"] not in {"active", "walking", "awaiting_walk_review"} and not (
        execution["state"] == "waiting" and abort_request(execution)
    ):
        raise QaPlanExecutionStateError("QA plan execution cannot heartbeat")
    require_execution_target(execution)
    from yoke_core.domain.qa_plan_execution_reentry import (
        require_execution_custody,
        heartbeat_checkpoint,
    )

    require_execution_custody(conn, execution)
    placeholder = marker(conn)
    now = utc_now()
    checkpoint = heartbeat_checkpoint(execution)
    conn.execute(
        "UPDATE qa_plan_executions SET heartbeat_at="
        f"{placeholder},release_reason={placeholder} WHERE id={placeholder}",
        (instant_parameter(conn, now), checkpoint, str(execution["id"])),
    )
    execution["release_reason"] = checkpoint
    from yoke_core.domain.qa_plan_host_leases import heartbeat_execution_hosts

    heartbeat_execution_hosts(conn, execution, now=now)
    if execution.get("test_machine_lease_id") is not None:
        heartbeat(conn, int(execution["test_machine_lease_id"]), now=now)
    else:
        conn.commit()
    execution["heartbeat_at"] = now


def set_plan_machine_lease(
    conn: Any,
    execution: dict[str, Any],
    *,
    lease_id: int,
) -> None:
    """Attach the server-acquired Test Machine lease to the durable plan.

    This is the commit point of the caller's lease acquisition: the lease
    release, acquisition and host-wait writes the caller left open commit
    here together with the attach, and a refused attach rolls all of them
    back so no acquired lease outlives a plan that cannot hold it.
    """
    from yoke_core.domain.qa_host_turns import cancel_host_waits

    with savepoint(conn, "_yoke_plan_machine_lease", owns=True):
        cancel_host_waits(conn, execution_ids=[str(execution["id"])])
        placeholder = marker(conn)
        now = utc_now()
        cursor = conn.execute(
            "UPDATE qa_plan_executions SET test_machine_lease_id="
            f"{placeholder},heartbeat_at={placeholder} WHERE id={placeholder} "
            "AND state='active' AND test_machine_lease_id IS NULL",
            (int(lease_id), instant_parameter(conn, now), str(execution["id"])),
        )
        if cursor.rowcount != 1:
            raise QaPlanExecutionStateError(
                "QA plan execution cannot attach the machine lease"
            )
        conn.commit()
    execution["test_machine_lease_id"] = int(lease_id)
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
        "walking",
        "awaiting_walk_review",
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
    if state in {"aborted", "error"}:
        from yoke_core.domain.qa_plan_execution_abort_state import require_host_restored

        require_host_restored(conn, execution, reason=reason, commit=commit)
    if state == "completed":
        from yoke_core.domain.qa_plan_execution_abort_state import abort_request

        if abort_request(execution):
            raise QaPlanExecutionStateError(
                "qa_abort_requested: completion is refused; keep the runner connected "
                "through cleanup and finish cancellation with yoke qa plan abort"
            )
    if state == "completed" and int(execution["cursor_ordinal"]) != len(
        execution["roster"]
    ):
        raise QaPlanExecutionStateError(
            "QA plan execution cannot complete before every case advances"
        )
    terminal_settlement = state in TERMINAL_PLAN_EXECUTION_STATES
    stopped_review = None
    if terminal_settlement:
        from yoke_core.domain.qa_host_turns import cancel_host_waits
        from yoke_core.domain.qa_plan_review import begin_plan_review

        cancel_host_waits(conn, execution_ids=[str(execution["id"])])
        if state in {"aborted", "error"}:
            from yoke_core.domain.qa_mission_stop_settlement import (
                settle_stopped_mission_dockets,
            )

            settle_stopped_mission_dockets(conn, execution, reason=reason)
        if state in {"aborted", "error"} and any(
            case.get("verdict_path") == "agent"
            for case in execution.get("roster") or []
        ):
            stopped_review = begin_plan_review(
                conn, execution, completed_captures_only=True
            )
        settle_unreviewed_execution_captures(conn, execution)
        record_inflight_case_failure(conn, execution, reason=reason)
    retain_lease = state in {"walking", "awaiting_walk_review"} and _mission_needs_retained_lease(
        execution
    )
    if not retain_lease:
        from yoke_core.domain.qa_plan_host_leases import release_execution_hosts

        release_execution_hosts(conn, execution, reason=reason)
    if execution.get("test_machine_lease_id") is not None and not retain_lease:
        release(
            conn,
            int(execution["test_machine_lease_id"]),
            reason,
            commit=False,
        )
    placeholder = marker(conn)
    now = utc_now()
    completed_at = None if state in {"waiting", "walking", "awaiting_walk_review"} else now
    conn.execute(
        "UPDATE qa_plan_executions SET state="
        f"{placeholder},completed_at={placeholder},heartbeat_at={placeholder},"
        f"release_reason={placeholder},test_machine_lease_id={placeholder} "
        f"WHERE id={placeholder}",
        (
            state,
            instant_parameter(conn, completed_at),
            instant_parameter(conn, now),
            reason,
            execution.get("test_machine_lease_id") if retain_lease else None,
            str(execution["id"]),
        ),
    )
    execution["state"] = state
    if not retain_lease:
        execution["test_machine_lease_id"] = None
    execution["completed_at"] = completed_at
    execution["release_reason"] = reason
    if terminal_settlement:
        dispose_execution_decisions(conn, execution, commit=False)
    if stopped_review is not None and stopped_review.get("state") == "pending":
        # The review outlives the walk; without an owner it strands the stage.
        from yoke_core.domain.qa_plan_agent_review_wake import (
            notify_stopped_capture_review,
        )

        notify_stopped_capture_review(
            conn, execution, bundle_id=str(stopped_review["bundle_id"])
        )
    if commit:
        if state in {"walking", "awaiting_walk_review"}:
            from yoke_core.domain.qa_plan_agent_review_wake import (
                notify_scoped_agent_review,
            )

            notify_scoped_agent_review(conn, execution)
        conn.commit()
        if state == "completed" and execution.get("deployment_stage"):
            from yoke_core.domain.deployment_qa_stage_settlement import (
                settle_execution,
            )

            settle_execution(conn, execution)
        if state in {"aborted", "error"} and execution.get("deployment_stage"):
            from yoke_core.domain.deployment_qa_shared_wait import (
                wake_shared_stage_waiters,
            )

            wake_shared_stage_waiters(conn, execution)
        if terminal_settlement and execution.get("item_id") is not None:
            # This row may be the one thing holding a member's close-out or
            # a settling run open. Its terminalization is the event that
            # unblocks them, so both retry here rather than waiting for a
            # hand re-drive of a gate that already passed.
            from yoke_core.domain.deployment_member_close_out_retry import (
                after_record_settled,
            )

            after_record_settled(conn, item_id=int(execution["item_id"]))


def reap_stale_plan_executions(
    conn: Any,
    *,
    now: Any | None = None,
) -> list[dict[str, Any]]:
    """Settle abandoned walks under their state-specific ownership rule.

    Waiting walks require durable owner-session end evidence. Other walks
    use heartbeat age, except while a live owner is deliberately parked.
    """
    if not _table_exists(conn, "qa_plan_executions"):
        return []
    candidates = [
        {
            "id": str(row[0]), "heartbeat_at": row[1],
            "session_id": row[2], "state": row[3],
        }
        for row in conn.execute(
            "SELECT id, heartbeat_at, session_id, state FROM qa_plan_executions "
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
            if not plan_execution_is_abandoned(conn, execution, now=now):
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
