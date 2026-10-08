"""Require terminal QA evidence to be settled and bound to the merged tree."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.qa_latest_execution import latest_executions
from yoke_core.domain.qa_merging_identity import (
    accepted_merging_shas,
)
from yoke_core.domain.qa_obligation_settlement import (
    item_supersession_settled,
    settled_obligation_sql,
)
from yoke_core.domain.qa_terminal_requirement_errors import (
    _recovery_instruction,
    requirement_issue_errors,
)
from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL
from yoke_core.domain.qa_terminal_records import (
    _blocking_requirement_rows,
    live_qa_leases,
)
from yoke_core.domain.schema_common import _table_exists


@dataclass(frozen=True)
class UnsettledQaRecord:
    """One QA record that must be resolved before an item becomes terminal."""

    kind: str
    record_id: str
    detail: str


@dataclass(frozen=True)
class BlockingRequirementIssue:
    """Why one terminal blocking requirement is not merge-authorizing."""

    requirement_id: str
    state: str
    detail: str
    recovery: str


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


def _render_shas(shas: Sequence[str]) -> str:
    return ", ".join(sha[:12] for sha in shas) if shas else "<missing>"


def _issue_for_requirement(
    requirement: dict[str, Any],
    *,
    accepted_shas: Sequence[str],
) -> BlockingRequirementIssue | None:
    requirement_id = str(requirement.get("id") or "<unknown>")
    review = requirement.get("human_review")
    if review:
        return BlockingRequirementIssue(
            requirement_id,
            "human-review",
            review["detail"],
            review["recovery"],
        )
    recovery = _recovery_instruction(requirement)
    if "post_deploy_consumed" in requirement:
        if requirement["post_deploy_consumed"]:
            return None
        return BlockingRequirementIssue(
            requirement_id,
            "post-deploy-unaccepted",
            "the admitted source copies are not accepted on the completion run",
            recovery,
        )
    run_id = requirement.get("run_id")
    if run_id is None:
        return BlockingRequirementIssue(
            requirement_id,
            "missing",
            "no materialized run exists",
            recovery,
        )
    verdict = str(requirement.get("verdict") or "").strip().lower()
    completed_at = str(requirement.get("completed_at") or "").strip()
    if verdict != "pass" or not completed_at:
        actual = str(
            requirement.get("case_outcome")
            or requirement.get("execution_status")
            or verdict
            or "pending"
        ).strip()
        reason = str(requirement.get("verdict_reason") or "").strip()
        reason_text = f"; reason: {reason}" if verdict == "undetermined" else ""
        return BlockingRequirementIssue(
            requirement_id,
            "incomplete",
            f"latest run #{run_id} concluded {actual!r}{reason_text}, not completed success",
            recovery,
        )
    run_sha = str(requirement.get("recorded_head_sha") or "").strip()
    if run_sha not in set(accepted_shas) or not run_sha:
        return BlockingRequirementIssue(
            requirement_id,
            "stale-sha",
            f"passing run #{run_id} recorded SHA {run_sha or '<missing>'}; "
            f"the merge verified {_render_shas(accepted_shas)}",
            recovery,
        )
    return None


def blocking_requirement_issues(
    requirements: list[dict[str, Any]],
    *,
    accepted_shas: Sequence[str],
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
        for requirement in blocking
        if (
            issue := _issue_for_requirement(
                requirement,
                accepted_shas=accepted_shas,
            )
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
        f"SELECT q.id FROM qa_requirements q WHERE q.item_id={placeholder} "
        f"AND NOT {settled_obligation_sql(conn, 'q')}",
        (int(item_id),),
    ).fetchall()
    attempts = latest_executions(conn, [int(row[0]) for row in requirements])
    run_rows = [row for row in attempts.values() if row["verdict"] is None]
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
        accepted_shas=accepted_merging_shas(conn, item_id),
        public_ref=public_ref,
        require_any=True,
    )
    errors = requirement_issue_errors(
        issues, public_ref=public_ref, target_status=target_status
    )
    return (
        {
            "success": False,
            "error_code": "GATE_QA_TERMINAL_VERDICT",
            "error": "\n".join(errors),
        }
        if errors
        else None
    )


__all__ = [
    "BlockingRequirementIssue",
    "UnsettledQaRecord",
    "blocking_requirement_issues",
    "find_unsettled_records",
    "requirement_issue_errors",
    "settlement_errors",
    "terminal_transition_result",
]
