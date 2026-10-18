"""Plan-phase QA gate predicates."""

from __future__ import annotations

from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.qa_gate_definitions import GateResult
from yoke_core.domain.qa_obligation_settlement import item_supersession_open_sql
from yoke_core.domain.qa_gate_preconditions import (
    QA_CORE_TABLES,
    qa_gate_precondition_result,
)
from yoke_core.domain.qa_review_waits import requirement_awaits_human_review
from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run


# Stage this gate guards. A requirement bound to a later stage stays with
# that stage's own gate; a row with no binding is still counted here.
_PLANNED_TRANSITION_ID = "planned"


def check_plan_simulation_satisfied(item_id: int, db_path: str) -> GateResult:
    """Refuse ``-> planned`` when plan-bound blocking verification is open.

    This is defense in depth for a workflow that records resolution
    narrative on a failing ``qa_runs`` row instead of recording a fresh
    passing run. Even if the trigger protecting completed QA runs is
    absent, this gate refuses to advance an item to ``planned`` until each
    blocking verification requirement bound to ``planned`` or to no
    transition has a separate passing run or an explicit waiver. A
    requirement bound to a later transition is left to that gate.
    """
    precondition = qa_gate_precondition_result(
        db_path,
        required_tables=QA_CORE_TABLES,
    )
    if precondition is not None:
        return precondition

    conn = connect(db_path)
    try:
        unsatisfied = query_rows(
            conn,
            f"""
            SELECT r.id, r.qa_kind FROM qa_requirements r
            WHERE r.item_id = %s
              AND r.qa_phase = 'verification'
              AND r.blocking_mode = 'blocking'
              AND (
                    r.workflow_transition_id IS NULL
                    OR r.workflow_transition_id = %s
              )
              AND r.waived_at IS NULL AND {item_supersession_open_sql(conn, "r")}
            ORDER BY r.id
            """,
            (item_id, _PLANNED_TRANSITION_ID),
        )
        unsatisfied = [
            row
            for row in unsatisfied
            if not has_current_passing_run(conn, int(row["id"]))
        ]
        review_waits = {
            int(row["id"]): requirement_awaits_human_review(conn, int(row["id"]))
            for row in unsatisfied
        }
    finally:
        conn.close()

    if not unsatisfied:
        return GateResult(passed=True)

    errors = [
        "Cannot advance to 'planned' -- blocking plan-phase verification "
        "requirement(s) have no passing run.",
        "Record fresh evidence with /yoke simulate or `yoke qa run add`, "
        "or waive the requirement with explicit operator authorization.",
    ]
    for row in unsatisfied:
        waiting = review_waits[int(row["id"])]
        errors.extend(
            [f"  - {waiting.detail}", f"    {waiting.recovery}"]
            if waiting
            else [f"  - Requirement #{row['id']} ({row['qa_kind']}): no passing run"]
        )
    return GateResult(passed=False, errors=errors)
