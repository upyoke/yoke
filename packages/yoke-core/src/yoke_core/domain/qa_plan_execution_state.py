"""Durable authority for ordered QA plan execution and resume."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.qa_plan_execution_authority import (
    PLAN_EXECUTION_STALE_SECONDS,
    require_plan_execution_abandon_authority,
    require_plan_execution_owner,
)
from yoke_core.domain.qa_plan_execution_continuation import skips_host_baseline
from yoke_core.domain.qa_plan_execution_lifecycle import (
    finish_plan_execution,
    heartbeat_plan_execution,
    reap_stale_plan_executions,
    set_plan_machine_lease,
)
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    build_execution_roster,
    canonical,
    lock_plan_execution,
    marker,
    plan_execution_view,
)
from yoke_core.domain.qa_plan_execution_target_snapshot import require_execution_target
from yoke_core.domain.qa_plan_execution_roster import expected_plan_case
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution


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
    require_execution_target(execution)

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
    "reap_stale_plan_executions",
    "require_plan_execution_abandon_authority",
    "require_plan_execution_owner",
    "set_plan_machine_lease",
    "skips_host_baseline",
]
