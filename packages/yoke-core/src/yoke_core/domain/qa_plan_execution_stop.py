"""A steering seat stops another session's live QA walk through its runner.

The owning runner is the only process that can put its host back: it holds
the lease, knows which case is in flight, and records the restore proof. So
a steering stop never settles a walk the runner still drives. It records the
same stop request an owner's host abort records; the runner reads it from
its next case check-in or host heartbeat, stops, cleans up and settles the
execution itself. Settling it here instead would leave the runner driving
the host while Yoke treats that host as free.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_execution_abort_reason import (
    ABORT_REASON_MAX_LENGTH,
    REASON_DETAIL_SEPARATOR,
)
from yoke_core.domain.qa_plan_execution_store import marker

#: The code a steering stop's reason opens with, ahead of its requester.
STEERING_STOP_REASON = "steering-stop-requested"
#: The only state in which a runner is driving the walk and must obey a stop.
RUNNER_DRIVEN_STATE = "active"


def execution_project_id(conn: Any, execution: Mapping[str, Any]) -> int:
    """The project whose steering seat may stop this execution."""
    p = marker(conn)
    if execution.get("item_id") is not None:
        sql, key = f"SELECT project_id FROM items WHERE id={p}", execution["item_id"]
    elif execution.get("deployment_run_id") is not None:
        sql = f"SELECT project_id FROM deployment_runs WHERE id={p}"
        key = execution["deployment_run_id"]
    else:
        sql = f"SELECT project_id FROM qa_plans WHERE id={p}"
        key = execution.get("standalone_plan_id")
    row = query_one(conn, sql, (key,))
    if row is None:
        raise ValueError(
            f"qa_execution_project_unknown: QA plan execution {execution.get('id')} "
            "names a subject with no project; read it with yoke qa plan get and "
            "report the row to steering"
        )
    return int(row["project_id"])


def steering_seat_covers(
    conn: Any, execution: Mapping[str, Any], *, session_id: str
) -> bool:
    """Whether the caller holds a live steering seat over this execution."""
    from yoke_core.domain.session_steering_authority import covering_session_seat

    target = {"project_id": execution_project_id(conn, execution)}
    return (
        covering_session_seat(conn, caller_session_id=session_id, target=target)
        is not None
    )


def steering_stop_reason(session_id: str, reason: str) -> str:
    """The durable reason naming who stopped the walk and why."""
    sep = REASON_DETAIL_SEPARATOR
    text = f"{STEERING_STOP_REASON}{sep}session {session_id}{sep}{reason}"
    return text[:ABORT_REASON_MAX_LENGTH]


def request_steering_stop(
    conn: Any,
    execution: dict[str, Any],
    *,
    actor_id: str | None,
    session_id: str,
    reason: str,
) -> dict[str, Any]:
    """Record the stop the owning runner obeys, and name it in the receipt.

    An execution that already carries a stop request keeps it: its time and
    interrupted case stay what the first request recorded.
    """
    from yoke_core.domain.qa_plan_execution_abort_state import (
        abort_request,
        owed_host_abort,
        record_abort_request,
    )

    request = abort_request(execution)
    if request is None:
        stop_reason = steering_stop_reason(session_id, reason)
        owed = owed_host_abort(conn, execution, reason=stop_reason)
        last = max(len(execution.get("roster") or []) - 1, 0)
        ordinal = (
            int(owed["ordinal"])
            if owed
            else min(int(execution["cursor_ordinal"]), last)
        )
        record_abort_request(
            conn,
            execution,
            {
                "reason": stop_reason,
                "ordinal": ordinal,
                "requested_by_session_id": session_id,
                "requested_by_actor_id": actor_id,
            },
        )
        conn.commit()
        request = abort_request(execution)
    from yoke_core.domain.qa_plan_execution_authority import (
        PLAN_EXECUTION_STALE_SECONDS,
    )

    owner = str(execution.get("session_id") or "")
    return {
        "outcome": "stop_requested",
        "execution_id": str(execution["id"]),
        "owner_session_id": owner,
        "request": dict(request or {}),
        "next": (
            f"Session {owner}'s runner stops this execution at its next case "
            "check-in or host heartbeat, cleans up its host and settles it as "
            "aborted with this reason. Nothing else is needed. If that session "
            "is gone, any session may abandon the execution once it has not "
            f"heartbeated for {PLAN_EXECUTION_STALE_SECONDS // 60} minutes."
        ),
    }


def settled_stop_reason(execution: Mapping[str, Any], reason: str) -> str:
    """The reason an abort settles with: a recorded stop names why it stopped."""
    from yoke_core.domain.qa_plan_execution_abort_state import abort_request

    return str((abort_request(execution) or {}).get("reason") or reason)


def stop_plan_execution(
    conn: Any,
    execution: dict[str, Any],
    *,
    actor_id: str | None,
    session_id: str,
    reason: str,
) -> dict[str, Any]:
    """Stop an execution the caller's abort authority already admitted.

    A caller that is neither the owner nor abandoning a left execution holds
    a steering seat. A walk its runner still drives gets a stop request; one
    no runner drives (waiting, or awaiting review) settles here under the
    steering reason. Every other abort settles here under its own reason, or
    the reason a recorded stop request already names.
    """
    from yoke_core.domain.qa_deployment_execution_cleanup import abort_reason
    from yoke_core.domain.qa_plan_execution_authority import (
        plan_execution_is_abandoned,
    )
    from yoke_core.domain.qa_plan_execution_state import (
        finish_plan_execution,
        plan_execution_view,
    )
    from yoke_core.domain.qa_plan_execution_store import same_owner

    steering = not same_owner(
        execution, actor_id=actor_id, session_id=session_id
    ) and not plan_execution_is_abandoned(conn, execution)
    if steering and execution["state"] == RUNNER_DRIVEN_STATE:
        stop = request_steering_stop(
            conn, execution, actor_id=actor_id, session_id=session_id, reason=reason
        )
        return {**plan_execution_view(conn, execution), "stop_request": stop}
    if steering:
        reason = steering_stop_reason(session_id, reason)
    finish_plan_execution(
        conn,
        execution,
        state="aborted",
        reason=abort_reason(conn, execution, settled_stop_reason(execution, reason)),
    )
    result = plan_execution_view(conn, execution)
    result["release_reason"] = execution.get("release_reason")
    return result


__all__ = [
    "RUNNER_DRIVEN_STATE",
    "STEERING_STOP_REASON",
    "execution_project_id",
    "request_steering_stop",
    "settled_stop_reason",
    "steering_seat_covers",
    "steering_stop_reason",
    "stop_plan_execution",
]
