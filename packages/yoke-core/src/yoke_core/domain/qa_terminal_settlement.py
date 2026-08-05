"""Require terminal QA evidence to be settled and bound to the merged tree."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


_LIVE_PLAN_EXECUTION_STATES = frozenset({"active", "waiting", "awaiting_agent_review"})
_LIVE_PLAN_EXECUTION_SQL = ", ".join(map(repr, sorted(_LIVE_PLAN_EXECUTION_STATES)))


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
    command: str


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


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def recorded_head_sha(raw_result: Any) -> str:
    """Return the exact commit a QA run says it verified."""
    payload = _json_object(raw_result)
    for key in ("verification_tree", "code_identity"):
        identity = payload.get(key)
        if isinstance(identity, dict) and identity.get("head_sha"):
            return str(identity["head_sha"]).strip()
        if isinstance(identity, dict) and identity.get("sha"):
            return str(identity["sha"]).strip()
    return ""


def _issue_for_requirement(
    requirement: dict[str, Any], *, expected_sha: str,
) -> BlockingRequirementIssue | None:
    requirement_id = str(requirement.get("id") or "<unknown>")
    command = f"yoke qa case run --requirement-id {requirement_id}"
    run_id = requirement.get("run_id")
    if run_id is None:
        return BlockingRequirementIssue(
            requirement_id, "missing", "no materialized run exists", command,
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
        return BlockingRequirementIssue(
            requirement_id,
            "incomplete",
            f"latest run #{run_id} concluded {actual!r}, not completed success",
            command,
        )
    run_sha = str(requirement.get("recorded_head_sha") or "").strip()
    if run_sha != expected_sha:
        return BlockingRequirementIssue(
            requirement_id,
            "stale-sha",
            f"passing run #{run_id} recorded SHA {run_sha or '<missing>'}; "
            f"merging SHA is {expected_sha or '<missing>'}",
            command,
        )
    return None


def blocking_requirement_issues(
    requirements: list[dict[str, Any]],
    *,
    expected_sha: str,
    item_ref: str,
    require_any: bool,
) -> list[BlockingRequirementIssue]:
    """Evaluate the latest run read model for a terminal blocking set."""
    declared = [
        requirement
        for requirement in requirements
        if str(requirement.get("blocking_mode") or "") == "blocking"
    ]
    blocking = [row for row in declared if not row.get("waived_at")]
    if not declared and require_any:
        return [BlockingRequirementIssue(
            "materialization",
            "missing",
            "no blocking QA requirement was materialized",
            f"yoke qa plan run --item {item_ref} "
            "--transition reviewing-implementation",
        )]
    return [
        issue
        for requirement in blocking
        if (issue := _issue_for_requirement(
            requirement, expected_sha=expected_sha,
        )) is not None
    ]


def requirement_issue_errors(
    issues: list[BlockingRequirementIssue],
    *,
    item_ref: str,
    target_status: str,
) -> list[str]:
    """Render actionable missing, incomplete, and stale-SHA refusals."""
    if not issues:
        return []
    errors = [
        f"Error: Cannot transition {item_ref} to {target_status!r} -- "
        f"{len(issues)} blocking QA requirement(s) lack a completed verdict "
        "for the merging commit.",
        "  A waiver is an explicit, recorded, requirement-scoped operator "
        "override; it is not part of the normal merge recipe.",
    ]
    errors.extend(
        f"  - Requirement #{issue.requirement_id} [{issue.state}]: "
        f"{issue.detail}. Run `{issue.command}`."
        for issue in issues
    )
    return errors


def _expected_item_sha(conn: Any, item_id: int) -> str:
    """Resolve the commit carried by Dash evidence or recorded lane history."""
    from yoke_core.domain.dash_execution import (
        DASH_EVIDENCE_SECTION,
        read_json_section,
    )

    evidence = read_json_section(conn, item_id=item_id, section=DASH_EVIDENCE_SECTION)
    if evidence and evidence.get("commit_sha"):
        return str(evidence["commit_sha"]).strip()
    from yoke_core.domain.schema_common import _column_exists

    if not (
        _table_exists(conn, "item_worktrees")
        and _column_exists(conn, "item_worktrees", "commit_sha")
    ):
        return ""
    placeholder = _placeholder(conn)
    row = conn.execute(
        "SELECT commit_sha FROM item_worktrees "
        f"WHERE item_id = {placeholder} AND commit_sha IS NOT NULL "
        "ORDER BY CASE WHEN state = 'active' THEN 0 ELSE 1 END, id DESC LIMIT 1",
        (int(item_id),),
    ).fetchone()
    return str(_row_value(row, "commit_sha", 0) or "").strip() if row else ""


def _blocking_requirement_rows(conn: Any, item_id: int) -> list[dict[str, Any]]:
    placeholder = _placeholder(conn)
    cursor = conn.execute(
        "SELECT q.id, q.blocking_mode, q.waived_at, r.id AS run_id, "
        "r.verdict, r.execution_status, r.case_outcome, r.completed_at, "
        "r.raw_result FROM qa_requirements q LEFT JOIN qa_runs r ON r.id = ("
        "SELECT latest.id FROM qa_runs latest "
        "WHERE latest.qa_requirement_id = q.id "
        "ORDER BY latest.id DESC LIMIT 1) "
        f"WHERE q.item_id = {placeholder} ORDER BY q.id",
        (int(item_id),),
    )
    columns = [str(column[0]) for column in cursor.description]
    rows = [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]
    for row in rows:
        row["recorded_head_sha"] = recorded_head_sha(row.pop("raw_result", None))
    return rows


def _workflow_requires_terminal_qa(workflow: Any, target_status: str) -> bool:
    return any(
        str(gate.get("id") or "") == "qa_verification"
        for gate in workflow.gates_for_stage(target_status)
    )


def find_unsettled_records(conn: Any, *, item_id: int) -> list[UnsettledQaRecord]:
    """Return active item QA records that a terminal transition would freeze."""
    if not (_table_exists(conn, "qa_requirements") and _table_exists(conn, "qa_runs")):
        return []
    placeholder = _placeholder(conn)
    run_rows = conn.execute(
        "SELECT r.id, r.qa_requirement_id, r.execution_status, r.raw_result "
        "FROM qa_runs r JOIN qa_requirements q ON q.id = r.qa_requirement_id "
        f"WHERE q.item_id = {placeholder} AND q.waived_at IS NULL "
        "AND r.verdict IS NULL ORDER BY r.id",
        (int(item_id),),
    ).fetchall()
    unsettled = [
        UnsettledQaRecord(
            kind="run",
            record_id=str(_row_value(row, "id", 0)),
            detail=(
                f"requirement {_row_value(row, 'qa_requirement_id', 1)}: "
                f"{_run_detail(row)}"
            ),
        )
        for row in run_rows
    ]
    if not _table_exists(conn, "qa_plan_executions"):
        return unsettled
    execution_rows = conn.execute(
        "SELECT id, state FROM qa_plan_executions "
        f"WHERE item_id = {placeholder} "
        f"AND state IN ({_LIVE_PLAN_EXECUTION_SQL}) "
        "ORDER BY created_at, id",
        (int(item_id),),
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
        "  Terminal QA records are immutable; finish or abort the execution, "
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

    item_ref = render_item_ref(conn, item_id)
    issues = blocking_requirement_issues(
        _blocking_requirement_rows(conn, item_id),
        expected_sha=_expected_item_sha(conn, item_id),
        item_ref=item_ref,
        require_any=True,
    )
    errors = requirement_issue_errors(issues, item_ref=item_ref, target_status=target_status)
    return {
        "success": False,
        "error_code": "GATE_QA_TERMINAL_VERDICT",
        "error": "\n".join(errors),
    } if errors else None


__all__ = [
    "BlockingRequirementIssue",
    "UnsettledQaRecord",
    "blocking_requirement_issues",
    "find_unsettled_records",
    "recorded_head_sha",
    "requirement_issue_errors",
    "settlement_errors",
    "terminal_transition_result",
]
