"""Durable authority for ordered QA plan execution and resume."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from yoke_core.domain import db_backend
from yoke_core.domain.coordination_leases import release_lease
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.qa_plan_execution_lifecycle import (
    finish_plan_execution,
    heartbeat_plan_execution,
    set_plan_machine_lease,
)
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    build_execution_roster,
    canonical,
    converge_plan_execution_insert_race,
    live_plan_execution_id,
    lock_plan_execution,
    marker,
    plan_execution_view,
    require_plan_execution_owner,
    resume_owned_plan_execution,
    roster_digest,
    same_owner,
    select_plan_execution,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)


PLAN_EXECUTION_STALE_SECONDS = 30 * 60


def _is_stale(value: Any, *, now: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return True
    return (now - parsed.astimezone(timezone.utc)).total_seconds() > (
        PLAN_EXECUTION_STALE_SECONDS
    )


def _release_stale_execution(
    conn: Any,
    execution: Mapping[str, Any],
    *,
    now: str,
) -> None:
    lease_id = execution.get("machine_lease_id")
    if lease_id is not None:
        release_lease(conn, int(lease_id), "qa-plan-execution-stale")
    placeholder = marker(conn)
    conn.execute(
        "UPDATE qa_plan_executions SET state='aborted',completed_at="
        f"{placeholder},release_reason='stale-heartbeat',machine_lease_id=NULL "
        f"WHERE id={placeholder}",
        (now, str(execution["id"])),
    )
    conn.commit()


@rollback_workflow_binding_write_errors
def begin_plan_execution(
    conn: Any,
    *,
    item_id: int | None = None,
    transition_id: str | None = None,
    deployment_run_id: str | None = None,
    actor_id: str | None,
    session_id: str,
) -> dict[str, Any]:
    """Create or resume the one live execution for a QA subject."""
    if not str(session_id or "").strip():
        raise QaPlanExecutionStateError(
            "ordered QA plan execution requires an owning session"
        )
    if (item_id is None) == (deployment_run_id is None):
        raise QaPlanExecutionStateError(
            "exactly one QA plan execution subject is required"
        )
    if item_id is not None and not str(transition_id or "").strip():
        raise QaPlanExecutionStateError(
            "item QA plan execution requires a workflow transition"
        )
    if deployment_run_id is not None and transition_id is not None:
        raise QaPlanExecutionStateError(
            "deployment-run QA plan execution has no workflow transition"
        )
    if item_id is not None:
        lock_item_workflow_bindings(conn, (int(item_id),))
    roster = build_execution_roster(
        conn,
        item_id=item_id,
        transition_id=transition_id,
        deployment_run_id=deployment_run_id,
    )
    digest = roster_digest(roster)
    existing_id = live_plan_execution_id(
        conn,
        item_id=item_id,
        transition_id=transition_id,
        deployment_run_id=deployment_run_id,
    )
    if existing_id is not None:
        existing = lock_plan_execution(conn, existing_id)
        if existing["state"] in {"active", "waiting"}:
            if same_owner(existing, actor_id=actor_id, session_id=session_id):
                return resume_owned_plan_execution(conn, existing, digest=digest)
            now_dt = datetime.now(timezone.utc)
            if not _is_stale(existing["heartbeat_at"], now=now_dt):
                conn.rollback()
                raise QaPlanExecutionStateError(
                    "another actor or session owns the active QA plan execution"
                )
            _release_stale_execution(conn, existing, now=iso8601_now())
            if item_id is not None:
                lock_item_workflow_bindings(conn, (int(item_id),))
            roster = build_execution_roster(
                conn,
                item_id=item_id,
                transition_id=transition_id,
                deployment_run_id=deployment_run_id,
            )
            digest = roster_digest(roster)

    execution_id = str(uuid4())
    now = iso8601_now()
    placeholder = marker(conn)
    try:
        conn.execute(
            "INSERT INTO qa_plan_executions("
            "id,item_id,deployment_run_id,transition_id,actor_id,session_id,"
            "roster_digest,"
            "roster_json,cursor_ordinal,state,created_at,heartbeat_at"
            f") VALUES ({', '.join([placeholder] * 12)})",
            (
                execution_id,
                int(item_id) if item_id is not None else None,
                deployment_run_id,
                transition_id,
                actor_id,
                session_id,
                digest,
                canonical(roster),
                0,
                "active",
                now,
                now,
            ),
        )
    except db_backend.integrity_error_types(conn) as exc:
        return converge_plan_execution_insert_race(
            conn,
            item_id=item_id,
            transition_id=transition_id,
            deployment_run_id=deployment_run_id,
            actor_id=actor_id,
            session_id=session_id,
            digest=digest,
            cause=exc,
        )
    conn.commit()
    return select_plan_execution(conn, execution_id, lock=False)


def expected_plan_case(
    execution: Mapping[str, Any],
    *,
    ordinal: int,
    requirement_id: int,
    allow_replay: bool = False,
) -> dict[str, Any]:
    """Validate an ordinal and return its immutable roster case."""
    cursor = int(execution["cursor_ordinal"])
    if ordinal != cursor and not (allow_replay and ordinal < cursor):
        raise QaPlanExecutionStateError(
            f"QA plan execution expects ordinal {cursor}, not {ordinal}"
        )
    roster = execution["roster"]
    if ordinal < 0 or ordinal >= len(roster):
        raise QaPlanExecutionStateError("QA plan execution ordinal is out of range")
    case = dict(roster[ordinal])
    if int(case["requirement_id"]) != int(requirement_id):
        raise QaPlanExecutionStateError(
            "QA plan execution ordinal targets a different requirement"
        )
    return case


def advance_plan_execution(
    conn: Any,
    execution: dict[str, Any],
    *,
    ordinal: int,
    requirement_id: int,
    result: Mapping[str, Any],
    commit: bool = True,
) -> dict[str, Any]:
    """Record one idempotent result and advance the durable cursor."""
    case = expected_plan_case(
        execution,
        ordinal=ordinal,
        requirement_id=requirement_id,
        allow_replay=True,
    )
    placeholder = marker(conn)
    existing_cursor = conn.execute(
        "SELECT requirement_id,result_json FROM qa_plan_execution_results "
        f"WHERE execution_id={placeholder} AND ordinal={placeholder}",
        (str(execution["id"]), int(ordinal)),
    )
    existing_row = existing_cursor.fetchone()
    if existing_row is None:
        existing = None
    elif hasattr(existing_row, "keys"):
        existing = {
            "requirement_id": existing_row["requirement_id"],
            "result_json": existing_row["result_json"],
        }
    else:
        existing = {
            "requirement_id": existing_row[0],
            "result_json": existing_row[1],
        }
    encoded = canonical(dict(result))
    if existing is not None:
        if (
            int(existing["requirement_id"]) != int(requirement_id)
            or str(existing["result_json"]) != encoded
        ):
            raise QaPlanExecutionStateError(
                "QA plan execution replay does not match its recorded result"
            )
        return case
    if execution["state"] != "active":
        raise QaPlanExecutionStateError("QA plan execution is not active")
    now = iso8601_now()
    conn.execute(
        "INSERT INTO qa_plan_execution_results("
        "execution_id,ordinal,requirement_id,result_json,completed_at"
        f") VALUES ({', '.join([placeholder] * 5)})",
        (str(execution["id"]), ordinal, requirement_id, encoded, now),
    )
    conn.execute(
        "UPDATE qa_plan_executions SET cursor_ordinal="
        f"{placeholder},heartbeat_at={placeholder} WHERE id={placeholder}",
        (ordinal + 1, now, str(execution["id"])),
    )
    execution["cursor_ordinal"] = ordinal + 1
    execution["heartbeat_at"] = now
    if commit:
        conn.commit()
    return case


__all__ = [
    "PLAN_EXECUTION_STALE_SECONDS",
    "QaPlanExecutionStateError",
    "advance_plan_execution",
    "begin_plan_execution",
    "build_execution_roster",
    "expected_plan_case",
    "finish_plan_execution",
    "heartbeat_plan_execution",
    "lock_plan_execution",
    "plan_execution_view",
    "require_plan_execution_owner",
    "set_plan_machine_lease",
]
