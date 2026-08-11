"""Audited terminalization of deployment runs.

The run-state update and its permanent audit event share one transaction so
operators never see a closed run without the evidence explaining who closed
it and why.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, iso8601_now, query_one
from yoke_core.domain.events import build_envelope
from yoke_core.domain.events_insert_sql import _INSERT_SQL
from yoke_core.domain.events_retired_name_guard import (
    assert_event_name_not_retired,
)
from yoke_core.domain.events_write_conn import event_insert_params
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
    terminalized_at: str
    terminalized_by_actor_id: Optional[int]
    terminalized_by_session_id: str
    event_id: str


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
    terminalized_at: str,
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
            "terminalized_at": terminalized_at,
            "terminalized_by_actor_id": actor_id,
            "terminalized_by_session_id": session_id,
        },
        created_at=terminalized_at,
    )
    envelope["actor_id"] = actor_id
    assert_event_name_not_retired(conn, TERMINALIZATION_EVENT)
    sql = _INSERT_SQL
    if not db_backend.connection_is_postgres(conn):
        sql = sql.replace("%s", "?")
    conn.execute(sql, event_insert_params(envelope, project_id))
    return str(envelope["event_id"])


def terminalize_run(
    run_id: str,
    *,
    disposition: str,
    reason: str,
    actor_id: Optional[int],
    session_id: str,
) -> RunTerminalization:
    """Close one active run and append its audit event atomically."""
    final_status = str(disposition).strip().lower()
    if final_status not in TERMINAL_DISPOSITIONS:
        raise RunTerminalizationRejected(
            "disposition must be one of: cancelled, failed"
        )
    clean_reason = str(reason).strip()
    if not clean_reason:
        raise RunTerminalizationRejected("reason must be non-empty")

    conn = connect()
    try:
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
                f"deployment run '{run_id}' has terminal status "
                f"'{prior_status}'"
            )

        terminalized_at = iso8601_now()
        conn.execute(
            "UPDATE deployment_runs SET status=%s, completed_at=%s "
            "WHERE id=%s",
            (final_status, terminalized_at, run_id),
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
            terminalized_at=terminalized_at,
        )
        conn.commit()
        return RunTerminalization(
            run_id=run_id,
            project=str(run["project"]),
            prior_status=prior_status,
            final_status=final_status,
            reason=clean_reason,
            terminalized_at=terminalized_at,
            terminalized_by_actor_id=actor_id,
            terminalized_by_session_id=session_id,
            event_id=event_id,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = [
    "RunTerminalization",
    "RunTerminalizationRejected",
    "TERMINALIZATION_EVENT",
    "TERMINAL_DISPOSITIONS",
    "terminalize_run",
]
