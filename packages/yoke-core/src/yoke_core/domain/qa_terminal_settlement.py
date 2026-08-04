"""Prevent terminal item transitions from freezing unfinished QA records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


_LIVE_PLAN_EXECUTION_STATES = frozenset({"active", "waiting", "awaiting_agent_review"})
_LIVE_PLAN_EXECUTION_SQL = ", ".join(
    f"'{state}'" for state in sorted(_LIVE_PLAN_EXECUTION_STATES)
)


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
    return (
        {
            "success": False,
            "error_code": "GATE_QA_TERMINAL_SETTLEMENT",
            "error": "\n".join(errors),
        }
        if errors
        else None
    )


__all__ = [
    "UnsettledQaRecord",
    "find_unsettled_records",
    "settlement_errors",
    "terminal_transition_result",
]
