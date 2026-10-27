"""Re-declare a machine-run case's starting state before anything has run it.

A case's starting state decides what the Test Machine holds when it begins,
so it is part of what every run of that case judged. While no run, plan
result, or live roster has touched the case, nothing has been judged against
it yet, and correcting the declaration rewrites no evidence. That is the one
window this write is open in; afterwards a corrected case replaces it.

The value is one JSON object carrying the three columns that must agree:
``{"starting_state": "as_is", "starting_state_reason": "..."}`` or
``{"starting_state": "baseline", "host_baseline": "fresh-host"}``. ``inherit``
depends on the plan's case order, which a single row cannot see, so the plan
is where that declaration lives.

An item row materialized from a plan is refused toward the plan as well: the
plan owns its definition, and a row-level change would be refused as stale
the next time the plan runs. A deployment run's admitted copy executes its
own row, so it is corrected in place. A source row's in-flight admitted
copies are rewritten with it, under the same unexecuted rule.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_contracts.qa_case_starting_state import (
    INHERIT,
    StartingStateError,
    normalize_starting_state,
)
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_admitted_case_reconciliation import (
    admitted_copies_in_flight,
)
from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL
from yoke_core.domain.qa_plan_execution_store import marker

STARTING_STATE_FIELD = "starting_state"
STARTING_STATE_COLUMNS = ("starting_state", "starting_state_reason", "host_baseline")
STARTING_STATE_CASE_EXECUTED = "starting_state_case_executed"
STARTING_STATE_PLAN_OWNED = "starting_state_plan_owned"
_INVALID = "payload_invalid"


def _declared(value: Any) -> Mapping[str, Any]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, Mapping):
        raise ValueError("expected a JSON object")
    unknown = sorted(set(parsed) - set(STARTING_STATE_COLUMNS))
    if unknown:
        raise ValueError(
            f"unknown keys {', '.join(unknown)}; "
            f"allowed: {', '.join(STARTING_STATE_COLUMNS)}"
        )
    return parsed


def _execution_refusal(conn: Any, row: Mapping[str, Any]) -> str:
    """Name what has already run this case, or return ``""``."""
    p = marker(conn)
    req_id = int(row["id"])
    for table, column, what in (
        ("qa_runs", "qa_requirement_id", "recorded QA runs"),
        ("qa_plan_execution_results", "requirement_id", "plan execution results"),
    ):
        found = query_one(
            conn, f"SELECT COUNT(*) AS n FROM {table} WHERE {column}={p}", (req_id,)
        )
        if found and int(found["n"]):
            return (
                f"requirement {req_id} has {int(found['n'])} {what}, and its "
                "starting state is part of what they judged. Add a corrected "
                "case with `yoke qa requirement add ... --starting-state as_is "
                "--starting-state-reason TEXT`, then retire this one with `yoke "
                f"qa requirement supersede --requirement-id {req_id} "
                "--superseded-by-requirement-id NEW --rationale TEXT`."
            )
    subject, subject_id = (
        ("deployment_run_id", row["deployment_run_id"])
        if row["deployment_run_id"]
        else ("item_id", row["item_id"])
    )
    if subject_id is None:
        return ""
    for execution in query_rows(
        conn,
        f"SELECT id, roster_json FROM qa_plan_executions WHERE {subject}={p} "
        f"AND state IN ({LIVE_PLAN_EXECUTION_SQL})",
        (subject_id,),
    ):
        roster = json.loads(execution["roster_json"] or "[]")
        if any(int(case.get("requirement_id") or 0) == req_id for case in roster):
            return (
                f"requirement {req_id} is frozen into the roster of live QA "
                f"execution {execution['id']}. Abort it with `yoke qa plan abort "
                f"--execution-id {execution['id']} --reason TEXT` (plus its "
                "subject flag), update the starting state, then run the plan "
                "again."
            )
    return ""


def prepare_starting_state(
    conn: Any, req_id: int, value: Any
) -> tuple[dict[str, Any], tuple[int, ...], str, str]:
    """Return ``(columns, admitted_copies, error_code, refusal)``."""
    subject = f"QA requirement {int(req_id)}"
    try:
        declared = _declared(value)
    except ValueError as exc:
        return {}, (), _INVALID, f"{subject}: starting_state value: {exc}"
    row = query_one(
        conn,
        "SELECT id, runner_id, item_id, plan_id, deployment_run_id "
        f"FROM qa_requirements WHERE id={marker(conn)}",
        (int(req_id),),
    )
    if row["plan_id"] is not None and row["deployment_run_id"] is None:
        return (
            {},
            (),
            STARTING_STATE_PLAN_OWNED,
            f"{subject} was materialized from QA plan {row['plan_id']}, which "
            "owns its starting state. Change the case's starting state with "
            "`yoke qa plan edit PLAN_SLUG --project P`, then refresh the row "
            "with `yoke qa plan rematerialize --item PREFIX-N --transition STAGE`.",
        )
    if declared.get("starting_state") == INHERIT:
        return (
            {},
            (),
            _INVALID,
            f"{subject}: starting_state 'inherit' depends on the plan's case "
            "order, so declare it on the plan case with `yoke qa plan edit`.",
        )
    baseline = str(declared.get("host_baseline") or "").strip() or None
    try:
        state, reason = normalize_starting_state(
            case_key=f"requirement {int(req_id)}",
            runner_id=row["runner_id"],
            method_config=row.get("method_config"),
            capability_requirements=row.get("capability_requirements"),
            host_baselines=[baseline] if baseline else [],
            starting_state=declared.get("starting_state"),
            starting_state_reason=declared.get("starting_state_reason"),
        )
    except StartingStateError as exc:
        return {}, (), _INVALID, f"{subject}: {exc}"
    copies = (
        ()
        if row["deployment_run_id"]
        else tuple(c.requirement_id for c in admitted_copies_in_flight(conn, req_id))
    )
    for target in (int(req_id), *copies):
        target_row = row if target == int(req_id) else _row(conn, target)
        refusal = _execution_refusal(conn, target_row)
        if refusal:
            return (
                {},
                (),
                STARTING_STATE_CASE_EXECUTED,
                (f"{STARTING_STATE_CASE_EXECUTED}: {refusal}"),
            )
    columns = {
        "starting_state": state,
        "starting_state_reason": reason,
        "host_baseline": baseline,
    }
    return columns, copies, "", ""


def _row(conn: Any, req_id: int) -> Mapping[str, Any]:
    return query_one(
        conn,
        "SELECT id, item_id, deployment_run_id FROM qa_requirements "
        f"WHERE id={marker(conn)}",
        (int(req_id),),
    )


def write_starting_state(
    conn: Any, requirement_ids: tuple[int, ...], columns: Mapping[str, Any]
) -> None:
    """Write the three agreeing columns on every named row."""
    p = marker(conn)
    assignments = ", ".join(f"{name}={p}" for name in STARTING_STATE_COLUMNS)
    for req_id in requirement_ids:
        conn.execute(
            f"UPDATE qa_requirements SET {assignments} WHERE id={p}",
            (*(columns[name] for name in STARTING_STATE_COLUMNS), int(req_id)),
        )


__all__ = [
    "STARTING_STATE_CASE_EXECUTED",
    "STARTING_STATE_COLUMNS",
    "STARTING_STATE_FIELD",
    "STARTING_STATE_PLAN_OWNED",
    "prepare_starting_state",
    "write_starting_state",
]
