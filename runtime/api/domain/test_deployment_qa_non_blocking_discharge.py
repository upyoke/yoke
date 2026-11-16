"""A member whose live cases are all non_blocking owes the stage gate nothing.

PLAT-468's only Stage case was set non_blocking and then waived; the gate kept
only blocking rows, read the member as having no cases at all, and held it on
"no concrete QA cases are materialized". Waived blocking cases still discharge,
and an unwaived failing blocking case still holds.
"""

from __future__ import annotations

from runtime.api.domain.deployment_qa_case_discharge_test_support import (
    MEMBER,
    STAGE,
    _acceptance,
    _corrected_case,
    _execute_stage,
    _seed,
    _status,
)

from yoke_core.domain.deployment_qa_stage_acceptance import (
    STAGE_CASES_UNRESOLVED,
    STAGE_DISCHARGED,
    member_cases_passed,
)
from yoke_core.domain.deployment_qa_stage_case_failures import (
    case_failures,
    obligations_fully_discharged,
)
from yoke_core.domain.qa_requirement_ops import waive_requirement


def _non_blocking(conn, requirement_id: int) -> None:
    conn.execute(
        "UPDATE qa_requirements SET blocking_mode='non_blocking' WHERE id=%s",
        (requirement_id,),
    )
    conn.commit()


def _waive(conn, requirement_id: int) -> None:
    waive_requirement(
        conn, requirement_id, "operator accepted the release", source="operator", force=True
    )


def _scope(conn, run_id: str, requirement_id: int) -> dict:
    digest = conn.execute(
        "SELECT execution_target_digest FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()["execution_target_digest"]
    return {
        "run_id": run_id,
        "stage_name": STAGE,
        "member_item_id": MEMBER,
        "execution_target_digest": digest,
    }


def test_only_non_blocking_case_discharges_the_member(test_db) -> None:
    run_id = "run-non-blocking-only"
    requirement_id = _seed(test_db, run_id)
    _non_blocking(test_db, requirement_id)
    scope = _scope(test_db, run_id, requirement_id)

    assert obligations_fully_discharged(test_db, **scope)
    assert case_failures(test_db, **scope) == []
    assert member_cases_passed(
        test_db, run_id, STAGE, MEMBER, scope["execution_target_digest"]
    )
    status = _status(test_db, run_id)
    assert status["accepted"], status["reasons"]
    assert not any("no concrete QA cases" in reason for reason in status["reasons"])
    assert _acceptance(test_db, run_id).state == STAGE_DISCHARGED


def test_waived_non_blocking_case_discharges_the_member(test_db) -> None:
    """The PLAT-468 shape: non_blocking, then waived."""
    run_id = "run-non-blocking-waived"
    requirement_id = _seed(test_db, run_id)
    _non_blocking(test_db, requirement_id)
    _waive(test_db, requirement_id)
    scope = _scope(test_db, run_id, requirement_id)

    assert obligations_fully_discharged(test_db, **scope)
    assert case_failures(test_db, **scope) == []
    assert _status(test_db, run_id)["accepted"]


def test_waived_blocking_case_still_discharges(test_db) -> None:
    run_id = "run-non-blocking-guard-waived"
    requirement_id = _seed(test_db, run_id)
    _waive(test_db, requirement_id)
    assert obligations_fully_discharged(test_db, **_scope(test_db, run_id, requirement_id))
    assert _acceptance(test_db, run_id).state == STAGE_DISCHARGED


def test_unwaived_failing_blocking_case_still_holds_beside_a_non_blocking_one(
    test_db,
) -> None:
    run_id = "run-non-blocking-guard-failing"
    blocking_id = _seed(test_db, run_id)
    advisory_id = _corrected_case(test_db, broken_id=blocking_id)
    _non_blocking(test_db, advisory_id)
    _execute_stage(test_db, run_id, {blocking_id: "fail", advisory_id: "pass"})
    scope = _scope(test_db, run_id, blocking_id)

    assert not obligations_fully_discharged(test_db, **scope)
    failures = case_failures(test_db, **scope)
    assert [failure.requirement_id for failure in failures] == [blocking_id]
    status = _status(test_db, run_id)
    assert not status["accepted"]
    assert _acceptance(test_db, run_id).state != STAGE_DISCHARGED


def test_unanswered_blocking_case_does_not_discharge(test_db) -> None:
    run_id = "run-non-blocking-guard-passed"
    requirement_id = _seed(test_db, run_id)
    assert not obligations_fully_discharged(
        test_db, **_scope(test_db, run_id, requirement_id)
    )
    assert _acceptance(test_db, run_id).state == STAGE_CASES_UNRESOLVED
