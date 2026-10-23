"""A recovery walk keeps the host place of the aborted shared walk before it.

A shared deployment-stage execution that held a Test Machine stood ahead of
every session that queued behind it. When it is aborted, the next execution of
the same run, stage and shared plan joins that host's line at the aborted
walk's place, so the recovery resumes next instead of joining the back. The
place is the earliest of the walk's granted waits and host leases, read from
the existing ``qa_test_machine_waits`` and ``work_claims`` records.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter, query_one
from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.work_claim_target_sql import conflict_match_clause
from yoke_core.domain.work_claim_targets import make_qa_admission_target


def _instant(conn: Any, value: Any) -> Any:
    return instant_parameter(conn, parse_instant(value)) if value else None


def held_host_place(
    conn: Any, execution: Mapping[str, Any], test_machine: str
) -> datetime | None:
    """When *execution* first stood for *machine*, or None if it never held it."""
    p = marker(conn)
    where, params = conflict_match_clause(
        conn, make_qa_admission_target(test_machine), alias="wc"
    )
    until = _instant(conn, execution.get("completed_at"))
    row = query_one(
        conn,
        "SELECT MIN(place) AS place FROM ("
        "SELECT w.queued_at AS place FROM qa_test_machine_waits w "
        f"WHERE w.qa_plan_execution_id={p} AND w.test_machine={p} "
        "AND w.state='granted' UNION ALL "
        f"SELECT wc.claimed_at FROM work_claims wc WHERE {where} "
        f"AND wc.session_id={p} AND wc.claimed_at>={p}"
        + (f" AND wc.claimed_at<={p}" if until is not None else "")
        + ") places",
        (
            str(execution["id"]),
            test_machine,
            *params,
            str(execution["session_id"]),
            _instant(conn, execution["created_at"]),
            *((until,) if until is not None else ()),
        ),
    )
    place = row["place"] if row is not None else None
    return parse_instant(place) if place else None


def inherited_host_place(
    conn: Any, execution: Mapping[str, Any], test_machine: str
) -> datetime | None:
    """The aborted shared walk's place on *machine* this execution recovers.

    Only a shared deployment-stage execution that has not yet held *machine*
    inherits, and only from the latest earlier execution of its run, stage
    and shared plan when that one was aborted while it held *machine*.
    """
    run, stage = execution.get("deployment_run_id"), execution.get("deployment_stage")
    if not run or not stage or execution.get("deployment_member_item_id") is not None:
        return None
    if held_host_place(conn, execution, test_machine) is not None:
        return None
    p = marker(conn)
    prior = query_one(
        conn,
        "SELECT id,session_id,state,created_at,completed_at FROM qa_plan_executions "
        f"WHERE deployment_run_id={p} AND deployment_stage={p} "
        f"AND deployment_member_item_id IS NULL AND id<>{p} AND created_at<={p} "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (run, stage, str(execution["id"]), _instant(conn, execution["created_at"])),
    )
    if prior is None or prior["state"] != "aborted":
        return None
    return held_host_place(conn, dict(prior), test_machine)


__all__ = ["held_host_place", "inherited_host_place"]
