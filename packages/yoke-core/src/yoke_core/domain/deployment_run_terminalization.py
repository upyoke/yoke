"""Audited terminalization of deployment runs.

The run-state update and its permanent audit event share one transaction so
operators never see a closed run without the evidence explaining who closed
it and why.

:func:`terminalize_run` owns its connection, for a caller that arrived with
nothing open. :func:`terminalize_run_on` is the same close against a
connection the caller already holds, so a decision that closes a run can do
it in the transaction that recorded the decision rather than in a second one
that could commit without it.

Closing a run also cancels the GitHub workflows it dispatched
(:mod:`yoke_core.domain.deployment_run_workflow_cancellation`). That talks to
GitHub, so it happens only after the close commits: :func:`terminalize_run`
does it itself, and a caller of :func:`terminalize_run_on` does it after its
own commit.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from yoke_contracts.timestamps import as_utc, format_instant, utc_now
from typing import Any, Dict, Optional, Tuple

from yoke_core.domain.deployment_runs_lock import lock_run
from yoke_core.domain.db_helpers import connect, instant_parameter, query_one
from yoke_core.domain.events import build_envelope
from yoke_core.domain.events_insert_sql import _INSERT_SQL
from yoke_core.domain.events_write_conn import (
    event_insert_params,
    write_event_row_on_conn,
)
from yoke_core.domain.runs import ACTIVE_RUN_STATUSES


TERMINAL_DISPOSITIONS = frozenset({"failed", "cancelled"})
TERMINALIZATION_EVENT = "DeploymentRunTerminalized"


@dataclass(frozen=True)
class RunTerminalization:
    run_id: str
    project: str
    prior_status: str
    final_status: str
    reason: str
    terminalized_at: datetime
    terminalized_by_actor_id: Optional[int]
    terminalized_by_session_id: str
    event_id: str
    #: One outcome per workflow the run dispatched, filled after the commit.
    workflow_cancellations: Tuple[Dict[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "terminalized_at", as_utc(self.terminalized_at))


class RunTerminalizationRejected(ValueError):
    """The requested run cannot be terminalized."""


def _append_event(
    conn: Any,
    *,
    run_id: str,
    project: str,
    project_id: int,
    prior_status: str,
    final_status: str,
    current_stage: str,
    reason: str,
    actor_id: Optional[int],
    session_id: str,
    terminalized_at: datetime,
) -> str:
    envelope = build_envelope(
        TERMINALIZATION_EVENT,
        event_kind="lifecycle",
        event_type="deployment_run",
        source_type="backend",
        session_id=session_id,
        severity="STATUS",
        outcome="completed",
        project=project,
        agent=str(actor_id) if actor_id is not None else session_id,
        context={
            "run_id": run_id,
            "prior_status": prior_status,
            "final_status": final_status,
            "current_stage": current_stage,
            "reason": reason,
            "terminalized_at": format_instant(terminalized_at),
            "terminalized_by_actor_id": actor_id,
            "terminalized_by_session_id": session_id,
        },
        created_at=terminalized_at,
    )
    envelope["actor_id"] = actor_id
    write_event_row_on_conn(
        conn, _INSERT_SQL, event_insert_params(envelope, project_id)
    )
    return str(envelope["event_id"])


def terminalize_run_on(
    conn: Any,
    run_id: str,
    *,
    disposition: str,
    reason: str,
    actor_id: Optional[int],
    session_id: str,
    terminalized_at: datetime | None = None,
) -> RunTerminalization:
    """Close one active run and append its audit event on *conn*.

    The caller owns the transaction: nothing here commits or rolls back, so
    a close recorded alongside other writes lands with them or not at all.
    """
    stamp = as_utc(terminalized_at) if terminalized_at is not None else utc_now()
    stored_stamp = instant_parameter(conn, stamp)
    final_status = str(disposition).strip().lower()
    if final_status not in TERMINAL_DISPOSITIONS:
        raise RunTerminalizationRejected(
            "disposition must be one of: cancelled, failed"
        )
    clean_reason = str(reason).strip()
    if not clean_reason:
        raise RunTerminalizationRejected("reason must be non-empty")

    lock_run(conn, run_id)
    run = query_one(
        conn,
        "SELECT dr.id, dr.project_id, p.slug AS project, dr.status, "
        "COALESCE(dr.current_stage, '') AS current_stage "
        "FROM deployment_runs dr "
        "JOIN projects p ON p.id = dr.project_id "
        "WHERE dr.id=%s FOR UPDATE",
        (run_id,),
    )
    if run is None:
        raise LookupError(f"deployment run '{run_id}' not found")
    prior_status = str(run["status"])
    if prior_status not in ACTIVE_RUN_STATUSES:
        raise RunTerminalizationRejected(
            f"deployment run '{run_id}' has terminal status '{prior_status}'"
        )

    conn.execute(
        "UPDATE deployment_runs SET status=%s, completed_at=%s WHERE id=%s",
        (final_status, stored_stamp, run_id),
    )
    from yoke_core.domain.deployment_qa_stage_wake_withdraw import (
        withdraw_deployment_qa_wait_wakes,
    )

    # No carried-work derivation here: it walks the repository host, and this
    # transaction holds the run row. A run that froze its composition already
    # recorded the answer; a read derives one for a run that never did.
    from yoke_core.domain.qa_deployment_run_settlement import settle_unsuccessful_run

    preserved = settle_unsuccessful_run(
        conn, run_id, reason=f"deployment run {run_id} {final_status}: {clean_reason}"
    )
    if not preserved:
        withdraw_deployment_qa_wait_wakes(
            conn, run_id=run_id, reason=f"run_terminal:{final_status}"
        )
    event_id = _append_event(
        conn,
        run_id=run_id,
        project=str(run["project"]),
        project_id=int(run["project_id"]),
        prior_status=prior_status,
        final_status=final_status,
        current_stage=str(run["current_stage"]),
        reason=clean_reason,
        actor_id=actor_id,
        session_id=session_id,
        terminalized_at=stamp,
    )
    return RunTerminalization(
        run_id=run_id,
        project=str(run["project"]),
        prior_status=prior_status,
        final_status=final_status,
        reason=clean_reason,
        terminalized_at=stamp,
        terminalized_by_actor_id=actor_id,
        terminalized_by_session_id=session_id,
        event_id=event_id,
    )


def terminalize_run(
    run_id: str,
    *,
    disposition: str,
    reason: str,
    actor_id: Optional[int],
    session_id: str,
) -> RunTerminalization:
    """Close one active run atomically, then cancel its dispatched workflows."""
    conn = connect()
    try:
        result = terminalize_run_on(
            conn,
            run_id,
            disposition=disposition,
            reason=reason,
            actor_id=actor_id,
            session_id=session_id,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    try:
        from yoke_core.domain.deployment_run_workflow_cancellation import (
            cancel_run_workflows,
        )

        cancellations = cancel_run_workflows(conn, run_id)
    finally:
        conn.close()
    return replace(result, workflow_cancellations=tuple(cancellations))


__all__ = [
    "RunTerminalization",
    "RunTerminalizationRejected",
    "TERMINALIZATION_EVENT",
    "TERMINAL_DISPOSITIONS",
    "terminalize_run",
    "terminalize_run_on",
]
