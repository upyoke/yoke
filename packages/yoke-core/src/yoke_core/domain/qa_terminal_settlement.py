"""Require terminal QA evidence to be settled for the item."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.qa_latest_execution import latest_executions
from yoke_core.domain.qa_requirement_issues import BlockingRequirementIssue, issue_for_requirement
from yoke_core.domain.qa_obligation_settlement import (
    item_supersession_settled,
    settled_obligation_sql,
)
from yoke_core.domain.qa_terminal_requirement_errors import (
    requirement_issue_errors,
)
from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL
from yoke_core.domain.qa_terminal_records import (
    _blocking_requirement_rows,
    answered_by_run_copy,
    live_qa_leases,
)
from yoke_core.domain.schema_common import _table_exists


@dataclass(frozen=True)
class UnsettledQaRecord:
    """One QA record that must be resolved before an item becomes terminal."""

    kind: str
    record_id: str
    detail: str




def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_value(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def _run_detail(row: Any) -> str:
    raw_result = _row_value(row, "raw_result", 3)
    try:
        payload = json.loads(str(raw_result or "{}"))
    except (TypeError, ValueError):
        payload = {}
    if isinstance(payload, dict) and payload.get("timed_out") is True:
        return "timed out without a verdict"
    execution_status = str(_row_value(row, "execution_status", 2) or "").strip()
    return (
        f"{execution_status} without a verdict"
        if execution_status
        else "pending verdict"
    )




def blocking_requirement_issues(
    requirements: list[dict[str, Any]],
    *,
    public_ref: str,
    require_any: bool,
) -> list[BlockingRequirementIssue]:
    """Evaluate the latest run read model for a terminal blocking set."""
    declared = [
        requirement
        for requirement in requirements
        if str(requirement.get("blocking_mode") or "") == "blocking"
    ]
    blocking = [
        row
        for row in declared
        if not row.get("waived_at")
        and not row.get("retracted_at")
        and not item_supersession_settled(row)
    ]
    if not declared and require_any:
        return [
            BlockingRequirementIssue(
                "materialization",
                "missing",
                "no blocking QA requirement was materialized",
                f"yoke qa plan run --item {public_ref} "
                "--transition reviewing-implementation",
            )
        ]
    return [
        issue
        for row in blocking
        if (
            issue := issue_for_requirement(row)
        )
        is not None
    ]


def _workflow_requires_terminal_qa(workflow: Any, target_status: str) -> bool:
    return any(
        str(gate.get("id") or "") == "qa_verification"
        for gate in workflow.gates_for_stage(target_status)
    )


def find_unsettled_records(conn: Any, *, item_id: int) -> list[UnsettledQaRecord]:
    """Return unsettled latest executions and active item QA plans."""
    if not (_table_exists(conn, "qa_requirements") and _table_exists(conn, "qa_runs")):
        return []
    placeholder = _placeholder(conn)
    requirements = conn.execute(
        "SELECT q.id,q.qa_phase,q.deployment_run_id FROM qa_requirements q "
        f"WHERE q.item_id={placeholder} AND NOT {settled_obligation_sql(conn, 'q')}",
        (int(item_id),),
    ).fetchall()
    attempts = latest_executions(conn, [int(row[0]) for row in requirements])
    sources = {
        int(row[0]) for row in requirements if row[1] == "post_deploy" and not row[2]
    }
    run_rows = [
        row
        for row in attempts.values()
        if row["verdict"] is None
        and not answered_by_run_copy(conn, item_id, row["qa_requirement_id"], sources)
    ]
    unsettled = [
        UnsettledQaRecord(
            kind="run",
            record_id=str(_row_value(row, "id", 0)),
            detail=(
                f"requirement {_row_value(row, 'qa_requirement_id', 1)} latest execution: "
                f"{_run_detail(row)}"
            ),
        )
        for row in run_rows
    ]
    unsettled.extend(
        UnsettledQaRecord(
            "host lease", str(lease_id), f"{owner} still owns a live host"
        )
        for lease_id, owner in live_qa_leases(conn, item_id)
    )
    if not _table_exists(conn, "qa_plan_executions"):
        return unsettled
    execution_rows = conn.execute(
        "SELECT id, state FROM qa_plan_executions "
        f"WHERE (item_id = {placeholder} OR deployment_member_item_id = {placeholder}) "
        f"AND state IN ({LIVE_PLAN_EXECUTION_SQL}) "
        "ORDER BY created_at, id",
        (int(item_id), int(item_id)),
    ).fetchall()
    unsettled.extend(
        UnsettledQaRecord(
            kind="plan execution",
            record_id=str(_row_value(row, "id", 0)),
            detail=f"{_row_value(row, 'state', 1)} execution remains active",
        )
        for row in execution_rows
    )
    return unsettled


def settlement_errors(
    conn: Any,
    *,
    item_id: int,
    target_status: str,
) -> list[str]:
    """Explain why the requested terminal transition cannot yet proceed."""
    from yoke_core.domain.project_identity import render_item_ref

    records = find_unsettled_records(conn, item_id=item_id)
    if not records:
        return []
    errors = [
        f"Error: Cannot transition {render_item_ref(conn, item_id)} "
        f"to {target_status!r} -- "
        f"{len(records)} QA record(s) are unsettled.",
        "  Only each requirement's latest execution counts; finish or abort it, "
        "record a verdict, or waive the requirement while its item claim is held.",
    ]
    errors.extend(
        f"  - {record.kind} #{record.record_id}: {record.detail}" for record in records
    )
    return errors


def terminal_transition_result(
    conn: Any,
    item_id: int,
    target_status: str,
    workflow: Any,
) -> dict[str, Any] | None:
    """Return the immutable-record blocker for a terminal transition."""
    from yoke_core.domain.item_terminal_resources import terminal_stage_ids

    if target_status not in terminal_stage_ids(workflow):
        return None
    errors = settlement_errors(
        conn,
        item_id=item_id,
        target_status=target_status,
    )
    if errors:
        return {
            "success": False,
            "error_code": "GATE_QA_TERMINAL_SETTLEMENT",
            "error": "\n".join(errors),
        }
    if not _workflow_requires_terminal_qa(workflow, target_status):
        return None
    from yoke_core.domain.project_identity import render_item_ref

    public_ref = render_item_ref(conn, item_id)
    issues = blocking_requirement_issues(
        _blocking_requirement_rows(conn, item_id),
        public_ref=public_ref,
        require_any=True,
    )
    errors = requirement_issue_errors(
        issues, action=f"transition {public_ref} to {target_status!r}"
    )
    if not errors:
        return None
    return {
        "success": False,
        "error_code": "GATE_QA_TERMINAL_VERDICT",
        "error": "\n".join(errors),
    }


__all__ = [
    "BlockingRequirementIssue",
    "UnsettledQaRecord",
    "blocking_requirement_issues",
    "find_unsettled_records",
    "requirement_issue_errors",
    "settlement_errors",
    "terminal_transition_result",
]
