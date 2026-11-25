"""Subject, ownership, and abandonment authority for QA plan executions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, NoReturn, Sequence

from yoke_contracts.timestamps import as_utc, utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_reclaim_progress import (
    newest_activity_stamp,
    tool_activity_stamp,
)


PLAN_EXECUTION_STALE_SECONDS = 30 * 60
#: Walks that cannot heartbeat while they wait; only their owner's end frees them.
HELD_PLAN_EXECUTION_STATES = frozenset({"waiting", "awaiting_walk_review"})


def lock_member_admission(conn: Any, run_id: str | None, member: int | None) -> None:
    """Serialize member cursor admission with audited membership removal.

    Callers read everything they need first; this lock covers only their
    re-check and write.
    """
    if run_id is None or member is None:
        return
    from yoke_core.domain.deployment_runs_lock import lock_run
    from yoke_core.domain.workflow_item_binding_lock import lock_item_workflow_bindings

    lock_item_workflow_bindings(conn, (int(member),))
    lock_run(conn, str(run_id))
    require_member_attached(conn, run_id, member)


def require_member_attached(conn: Any, run_id: str | None, member: int | None) -> None:
    """Refuse a member that has left the run; under the run lock this holds."""
    if run_id is None or member is None:
        return
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    if (
        conn.execute(
            f"SELECT 1 FROM deployment_run_items WHERE run_id={marker} AND item_id={marker}",
            (str(run_id), int(member)),
        ).fetchone()
        is None
    ):
        _fail(
            f"QA member {render_item_ref(conn, member)} is no longer attached to run {run_id!r}; "
            "wait for its next release instead of starting this execution"
        )


def _fail(message: str) -> NoReturn:
    from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError

    raise QaPlanExecutionStateError(message)


def walk_activity_rows(
    conn: Any, walks: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Add each walk's latest heartbeat or owner/child tool call.

    Batch the owner read for sweep and fleet roster pages. A walk without
    an owner row uses its own heartbeat.
    """
    owners = sorted({str(walk["session_id"]) for walk in walks if walk.get("session_id")})
    activity_by_owner = {}
    if owners and _table_exists(conn, "harness_sessions"):
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        rows = query_rows(
            conn,
            "SELECT session_id, last_tool_call_at, last_child_tool_call_at "
            f"FROM harness_sessions WHERE session_id IN ({','.join([p] * len(owners))})",
            tuple(owners),
        )
        activity_by_owner = {str(row["session_id"]): tool_activity_stamp(row) for row in rows}
    return [
        {
            **walk,
            "activity_at": newest_activity_stamp(
                walk.get("heartbeat_at"), activity_by_owner.get(str(walk.get("session_id")))
            ),
        }
        for walk in walks
    ]


def walk_silent_seconds(activity_at: datetime | None, now: datetime) -> float | None:
    """Seconds since the walk's latest activity, if any was recorded."""
    return None if activity_at is None else (as_utc(now) - activity_at).total_seconds()


def plan_execution_is_stale(
    conn: Any,
    execution: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """Report whether an execution has stopped reporting progress."""
    observed = as_utc(now) if now is not None else utc_now()
    if "activity_at" not in execution:
        (execution,) = walk_activity_rows(conn, [execution])
    silent = walk_silent_seconds(execution["activity_at"], observed)
    return silent is None or silent >= PLAN_EXECUTION_STALE_SECONDS


def owning_session_is_parked(conn: Any, execution: Mapping[str, Any]) -> bool:
    """Report whether a live owning session has declared a deliberate wait.

    A parked session is present and waiting on purpose -- an operator told
    its walker to hold. The park is only ever an answer for a session that
    is still there, so a session that has ended stops shielding whatever it
    owned no matter what mode its last row recorded.
    """
    from yoke_core.domain.session_mode import session_is_parked

    session_id = str(execution.get("session_id") or "")
    if not session_id or not _table_exists(conn, "harness_sessions"):
        return False
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT mode FROM harness_sessions "
        f"WHERE session_id={marker} AND ended_at IS NULL",
        (session_id,),
    ).fetchone()
    if row is None:
        return False
    return session_is_parked(row["mode"] if hasattr(row, "keys") else row[0])


def owning_session_has_ended(conn: Any, execution: Mapping[str, Any]) -> bool:
    """Require durable session-end evidence before abandoning a queued walk."""

    session_id = str(execution.get("session_id") or "")
    if not session_id or not _table_exists(conn, "harness_sessions"):
        return False
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    return conn.execute(
        "SELECT 1 FROM harness_sessions "
        f"WHERE session_id={marker} AND ended_at IS NOT NULL",
        (session_id,),
    ).fetchone() is not None


def plan_execution_is_abandoned(
    conn: Any,
    execution: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """All walks follow owner lifetime, and active walks also follow progress.

    Nothing heartbeats a walk that is waiting or awaiting walk review, and a
    wake can change the owner's mode. Only an explicit session end abandons
    a held execution. Other states also use the activity clock and the live
    parked-owner exemption.
    """
    if owning_session_has_ended(conn, execution):
        return True
    if execution.get("state") in HELD_PLAN_EXECUTION_STATES:
        return False
    if not plan_execution_is_stale(conn, execution, now=now):
        return False
    return not owning_session_is_parked(conn, execution)


def require_plan_execution_subject(
    execution: Mapping[str, Any],
    *,
    item_id: int | None = None,
    deployment_run_id: str | None = None,
    deployment_stage: str | None = None,
    deployment_member_item_id: int | None = None,
) -> None:
    """Bind an execution mutation to exactly the subject the caller named."""
    if (
        item_id is None
        and deployment_run_id is None
        and execution.get("standalone_plan_id") is not None
    ):
        return
    if (item_id is None) == (deployment_run_id is None):
        _fail("exactly one QA plan execution subject is required")
    if item_id is not None and (
        execution.get("item_id") is None or int(execution["item_id"]) != int(item_id)
    ):
        _fail("QA plan execution belongs to a different item")
    if deployment_run_id is not None and str(
        execution.get("deployment_run_id") or ""
    ) != str(deployment_run_id):
        _fail("QA plan execution belongs to a different deployment run")
    if deployment_stage is not None and str(
        execution.get("deployment_stage") or ""
    ) != str(deployment_stage):
        _fail("QA plan execution belongs to a different deployment stage")
    if deployment_member_item_id is not None and int(
        execution.get("deployment_member_item_id") or 0
    ) != int(deployment_member_item_id):
        _fail("QA plan execution belongs to a different deployment member")


def require_plan_execution_owner(
    execution: Mapping[str, Any],
    *,
    conn: Any | None = None,
    item_id: int | None = None,
    deployment_run_id: str | None = None,
    deployment_stage: str | None = None,
    deployment_member_item_id: int | None = None,
    actor_id: str | None,
    session_id: str,
    reviewing: bool = False,
    completed_replay: bool = False,
) -> None:
    """Bind every execution mutation to its subject, actor, and session."""
    from yoke_core.domain.qa_plan_execution_store import same_owner

    require_plan_execution_subject(
        execution,
        item_id=item_id,
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
    )
    if not same_owner(execution, actor_id=actor_id, session_id=session_id):
        _fail(
            "qa_execution_owner_mismatch: QA plan execution belongs to a different "
            "actor or session; if its owner has ended, acquire the item work claim "
            "and run yoke qa plan adopt with the same subject and --execution-id "
            f"{execution.get('id', 'ID')} --reason TEXT, then retry"
        )
    if completed_replay:
        return
    from yoke_core.domain.qa_plan_execution_abort_reason import (
        member_removal_pending,
    )

    # A removed member's target left the run; its cleanup still reports here.
    if execution.get("deployment_stage") is not None and not member_removal_pending(
        dict(execution)
    ):
        if conn is None:
            _fail("scoped deployment QA mutation requires database authority")
        from yoke_core.domain.deployment_qa_execution_target import (
            validate_deployment_execution_target,
        )

        try:
            validate_deployment_execution_target(
                conn,
                execution,
                require_active=not (
                    reviewing and execution["state"] in {"aborted", "error"}
                ),
            )
        except ValueError as exc:
            _fail(str(exc))


def plan_execution_abort_authority(
    conn: Any,
    execution: Mapping[str, Any],
    *,
    item_id: int | None = None,
    deployment_run_id: str | None = None,
    actor_id: str | None,
    session_id: str,
    now: datetime | None = None,
) -> str:
    """Name how this caller may stop an execution, or refuse.

    ``owner``: the owning session stops its own walk. ``abandon``: nobody is
    holding the execution any more. The walk went silent without a park, or
    its held owner ended. Any caller may settle it. ``steering``: a
    live steering seat stops a walk another session still drives; the stop
    goes through the runner, which cleans up its host and settles it.
    ``launcher`` grants the same stop to the live requester of this worker.
    """
    from yoke_core.domain.qa_plan_execution_store import same_owner
    from yoke_core.domain.qa_plan_execution_stop import (
        execution_project_id,
        steering_seat_covers,
    )

    require_plan_execution_subject(
        execution,
        item_id=item_id,
        deployment_run_id=deployment_run_id,
    )
    if same_owner(execution, actor_id=actor_id, session_id=session_id):
        return "owner"
    parked = owning_session_is_parked(conn, execution)
    if plan_execution_is_abandoned(conn, execution, now=now):
        return "abandon"
    from yoke_core.domain.session_launch_report_backstop import is_live_launcher

    if is_live_launcher(conn, owner=str(execution["session_id"]), caller=session_id):
        return "launcher"
    if steering_seat_covers(conn, execution, session_id=session_id):
        return "steering"
    from yoke_core.domain.session_steering_authority import steering_authority_message

    holding = (
        "is parked and still holding this walk"
        if parked
        else f"is {str(execution.get('state')).replace('_', ' ')} with a live owner"
        if execution.get("state") in HELD_PLAN_EXECUTION_STATES
        else "is still reporting progress"
    )
    _fail(
        "qa_execution_stop_requires_steering: QA plan execution "
        f"{execution.get('id')} belongs to session "
        f"{str(execution.get('session_id') or '')!r}, which {holding}. Stopping "
        "it from another session requires its live launcher or a covering steering seat. "
        f"{steering_authority_message(execution_project_id(conn, execution))} "
        "Then rerun this abort: it records a stop that the owning runner obeys "
        "at its next case or heartbeat. Without a seat, ask the owning session "
        "to abort its own execution. A walk that is waiting or awaiting walk "
        "review may be abandoned once its owner ends. Active walks may also be abandoned after "
        f"{PLAN_EXECUTION_STALE_SECONDS // 60} minutes without a heartbeat or owner tool activity "
        "unless its owner is parked"
    )


__all__ = [
    "HELD_PLAN_EXECUTION_STATES",
    "PLAN_EXECUTION_STALE_SECONDS",
    "owning_session_is_parked",
    "plan_execution_abort_authority",
    "plan_execution_is_abandoned",
    "plan_execution_is_stale",
    "require_plan_execution_owner",
    "require_plan_execution_subject",
    "walk_activity_rows",
    "walk_silent_seconds",
]
