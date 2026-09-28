"""A corrected QA case declared to replace an exact failed one.

The failed case keeps blocking but leaves the roster, so no later execution
captures or reviews it again; the corrected case's passing independent
verdict supersedes it on that verdict's own transaction, and a failing one
leaves it blocking with its evidence.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
    seed_member_qa_case,
)
from runtime.api.fixtures.qa_declared_replacement_fixture import (
    corrected_case,
    declare,
    requirement_row,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.qa_deployment_case_content_refresh import (
    declare_refreshed_replacements,
)
from yoke_core.domain.qa_plan_execution_roster import ordered_plan_requirements
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_requirement_replacement import (
    QaReplacementError,
    discharge_declared_replacements,
)

MEMBER = 9811


def _pass(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """Execute the member's roster to a pass, discharging on the same commit."""
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
        actor_id="2",
        session_id="member-qa",
    )
    passed: list[int] = []
    for ordinal, entry in enumerate(execution["roster"]):
        requirement_id = int(entry["requirement_id"])
        qa_run_id = record_case_verdict(conn, requirement_id, "pass", evidence=True)
        advance_plan_execution(
            conn,
            execution,
            ordinal=ordinal,
            requirement_id=requirement_id,
            result={
                "requirement_id": requirement_id,
                "verdict": "pass",
                "case_outcome": "passed",
                "run_id": qa_run_id,
            },
        )
        passed.append(requirement_id)
    discharged = discharge_declared_replacements(conn, passed)
    finish_plan_execution(conn, execution, state="completed", reason="test-complete")
    conn.commit()
    return [receipt for receipt, _ in discharged]


def _roster(conn: Any, run_id: str) -> list[int]:
    return [
        int(row["requirement_id"])
        for row in ordered_plan_requirements(
            conn,
            deployment_run_id=run_id,
            deployment_stage=ITEM_QA_STAGE,
            deployment_member_item_id=MEMBER,
        )
    ]


def _status(conn: Any, run_id: str) -> dict[str, Any]:
    return deployment_qa_stage_status(
        conn, run_id=run_id, stage_name=ITEM_QA_STAGE, member_item_id=MEMBER
    )


def _failed_with_correction(conn: Any, run_id: str) -> tuple[int, int]:
    failed_id = seed_member_qa_case(conn, run_id=run_id, member_item_id=MEMBER)
    record_case_verdict(conn, failed_id, "fail", evidence=True)
    corrected_id = corrected_case(conn, failed_id=failed_id, case_key="smoke-fixed")
    declare(conn, failed_id, "smoke-fixed", [corrected_id])
    return failed_id, corrected_id


def test_declared_case_leaves_the_roster_but_keeps_blocking(test_db) -> None:
    run_id = "run-replacement-declared"
    failed_id, corrected_id = _failed_with_correction(test_db, run_id)

    assert requirement_row(test_db, failed_id)["replacement_requirement_id"] == corrected_id
    assert _roster(test_db, run_id) == [corrected_id]
    status = _status(test_db, run_id)
    assert not status["accepted"]
    assert any(
        f"#{failed_id}" in reason and f"declared replacement #{corrected_id}" in reason
        for reason in status["reasons"]
    ), status["reasons"]


def test_passing_replacement_supersedes_the_failed_case(test_db) -> None:
    run_id = "run-replacement-pass"
    failed_id, corrected_id = _failed_with_correction(test_db, run_id)

    receipts = _pass(test_db, run_id)

    assert [receipt["requirement_id"] for receipt in receipts] == [failed_id]
    row = requirement_row(test_db, failed_id)
    assert row["superseded_by_requirement_id"] == corrected_id
    assert row["supersession_source"] == "agent"
    assert f"requirement {corrected_id}" in row["supersession_rationale"]
    assert row["waived_at"] is None
    assert _roster(test_db, run_id) == [corrected_id]
    status = _status(test_db, run_id)
    assert status["accepted"], status["reasons"]


def test_failing_replacement_leaves_the_failed_case_blocking(test_db) -> None:
    run_id = "run-replacement-fail"
    failed_id, corrected_id = _failed_with_correction(test_db, run_id)

    record_case_verdict(test_db, corrected_id, "fail", evidence=True)
    assert discharge_declared_replacements(test_db, []) == []
    test_db.commit()

    row = requirement_row(test_db, failed_id)
    assert row["superseded_by_requirement_id"] is None
    assert row["replacement_requirement_id"] == corrected_id
    status = _status(test_db, run_id)
    assert not status["accepted"]
    assert any(f"#{failed_id}" in reason for reason in status["reasons"])
    assert any(f"#{corrected_id}" in reason for reason in status["reasons"])


def test_retry_correction_inherits_every_earlier_attempt(test_db) -> None:
    run_id = "run-replacement-retry"
    failed_id, first_fix = _failed_with_correction(test_db, run_id)
    record_case_verdict(test_db, first_fix, "fail", evidence=True)
    second_fix = corrected_case(test_db, failed_id=first_fix, case_key="smoke-fixed-2")

    declare(test_db, first_fix, "smoke-fixed-2", [second_fix])

    assert requirement_row(test_db, failed_id)["replacement_requirement_id"] == second_fix
    assert requirement_row(test_db, first_fix)["replacement_requirement_id"] == second_fix
    assert _roster(test_db, run_id) == [second_fix]

    receipts = _pass(test_db, run_id)
    assert sorted(receipt["requirement_id"] for receipt in receipts) == sorted(
        [failed_id, first_fix]
    )
    status = _status(test_db, run_id)
    assert status["accepted"], status["reasons"]


def test_declaration_refuses_what_it_cannot_ground(test_db) -> None:
    run_id = "run-replacement-refusals"
    failed_id = seed_member_qa_case(test_db, run_id=run_id, member_item_id=MEMBER)
    corrected_id = corrected_case(test_db, failed_id=failed_id, case_key="smoke-fixed")

    with pytest.raises(QaReplacementError, match="matched none"):
        declare(test_db, failed_id, "no-such-case", [corrected_id])
    test_db.rollback()

    record_case_verdict(test_db, failed_id, "pass", evidence=True)
    with pytest.raises(QaReplacementError, match="already passed"):
        declare(test_db, failed_id, "smoke-fixed", [corrected_id])
    test_db.rollback()
    assert requirement_row(test_db, failed_id)["replacement_requirement_id"] is None


def test_refreshed_case_is_declared_the_replacement_of_its_failed_rows(test_db) -> None:
    run_id = "run-replacement-refresh"
    failed_id = seed_member_qa_case(test_db, run_id=run_id, member_item_id=MEMBER)
    record_case_verdict(test_db, failed_id, "fail", evidence=True)
    base_key = test_db.execute(
        "SELECT plan_case_key FROM qa_requirements WHERE id=%s", (failed_id,)
    ).fetchone()[0]
    refreshed_id = corrected_case(
        test_db, failed_id=failed_id, case_key=f"{base_key}@0123456789ab"
    )

    declare_refreshed_replacements(test_db, [refreshed_id])
    test_db.commit()

    assert requirement_row(test_db, failed_id)["replacement_requirement_id"] == refreshed_id
    assert _roster(test_db, run_id) == [refreshed_id]
