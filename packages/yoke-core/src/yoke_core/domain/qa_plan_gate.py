"""Plan-phase QA gate predicates."""

from __future__ import annotations

from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.qa_gate_definitions import GateResult
from yoke_core.domain.qa_gate_preconditions import (
    QA_CORE_TABLES,
    qa_gate_precondition_result,
)


def check_plan_simulation_satisfied(
    item_id: int, db_path: str
) -> GateResult:
    """Refuse ``-> planned`` when blocking verification evidence is unsatisfied.

    This is defense in depth for a workflow that records resolution
    narrative on a failing ``qa_runs`` row instead of recording a fresh
    passing run. Even if the trigger protecting completed QA runs is
    absent, this gate refuses to advance an item to ``planned`` until each
    blocking verification requirement has a separate passing run or an
    explicit waiver.
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
            """
            SELECT r.id, r.qa_kind FROM qa_requirements r
            WHERE r.item_id = %s
              AND r.qa_phase = 'verification'
              AND r.blocking_mode = 'blocking'
              AND r.waived_at IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM qa_runs qr
                WHERE qr.qa_requirement_id = r.id
                  AND qr.verdict = 'pass'
              )
            ORDER BY r.id
            """,
            (item_id,),
        )
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
        errors.append(
            f"  - Requirement #{row['id']} ({row['qa_kind']}): no passing run"
        )
    return GateResult(passed=False, errors=errors)
