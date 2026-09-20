"""A failed case and an unrun one are different answers about a stage.

Both leave the stage unaccepted, and that is deliberately unchanged. What
changed is what the stage says about itself: a determinate failing verdict
reports ``blocked`` and names its requirements, an unrun case reports
``waiting``, and a passing case the gate cannot see evidence for is named
as its own thing rather than folded into either.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
    seed_member_qa_case,
)
from yoke_core.domain.deployment_qa_case_failure_kinds import (
    FAILURE_PASSED_WITHOUT_EVIDENCE,
    FAILURE_RED,
    FAILURE_UNDETERMINED,
    FAILURE_UNRUN,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_outcome import (
    OUTCOME_BLOCKED,
    OUTCOME_WAITING,
)

MEMBER = 9901


def _status(conn: Any, run_id: str) -> dict[str, Any]:
    return deployment_qa_stage_status(
        conn, run_id=run_id, stage_name=ITEM_QA_STAGE, member_item_id=MEMBER
    )


def _kinds(status: dict[str, Any]) -> list[str]:
    return [failure["kind"] for failure in status["case_failures"]]


def _record_undetermined(conn: Any, requirement_id: int) -> None:
    """An undecided verdict, which the schema requires a reason with."""
    now = "2026-09-18T00:02:00Z"
    conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "verdict_reason,started_at,completed_at,created_at) "
        "VALUES (%s,'worktree_run','plan_case','undetermined',"
        "'the runner could not decide',%s,%s,%s)",
        (int(requirement_id), now, now, now),
    )
    conn.commit()


def test_an_unrun_case_reports_waiting(test_db) -> None:
    seed_member_qa_case(test_db, run_id="run-red-unrun", member_item_id=MEMBER)

    status = _status(test_db, "run-red-unrun")

    assert status["accepted"] is False
    assert status["outcome"] == OUTCOME_WAITING
    assert _kinds(status) == [FAILURE_UNRUN]
    assert any("latest verdict is missing" in r for r in status["reasons"])


def test_a_failed_case_reports_blocked_and_names_its_requirement(test_db) -> None:
    requirement_id = seed_member_qa_case(
        test_db, run_id="run-red-fail", member_item_id=MEMBER
    )
    record_case_verdict(test_db, requirement_id, "fail", evidence=False)

    status = _status(test_db, "run-red-fail")

    # Unchanged: a red stage is exactly as unacceptable as a waiting one.
    assert status["accepted"] is False
    assert status["outcome"] == OUTCOME_BLOCKED
    assert _kinds(status) == [FAILURE_RED]
    assert status["case_failures"][0]["requirement_id"] == requirement_id
    assert any(
        f"cannot finish as it stands" in reason and f"#{requirement_id}" in reason
        for reason in status["reasons"]
    )


def test_an_errored_case_is_red_too(test_db) -> None:
    requirement_id = seed_member_qa_case(
        test_db, run_id="run-red-error", member_item_id=MEMBER
    )
    record_case_verdict(test_db, requirement_id, "error", evidence=False)

    status = _status(test_db, "run-red-error")

    assert status["outcome"] == OUTCOME_BLOCKED
    assert _kinds(status) == [FAILURE_RED]


def test_an_undetermined_case_is_waiting_on_a_judgment_not_red(test_db) -> None:
    requirement_id = seed_member_qa_case(
        test_db, run_id="run-red-undetermined", member_item_id=MEMBER
    )
    _record_undetermined(test_db, requirement_id)

    status = _status(test_db, "run-red-undetermined")

    assert status["outcome"] == OUTCOME_WAITING
    assert _kinds(status) == [FAILURE_UNDETERMINED]


def test_a_passing_case_without_evidence_is_named_as_its_own_state(test_db) -> None:
    """Neither red nor unrun: the owner sees green and the gate does not.

    Re-running it produces another passing case with the same problem, so
    folding it into "unrun" would send its owner to do the one thing that
    cannot help.
    """
    requirement_id = seed_member_qa_case(
        test_db, run_id="run-red-no-evidence", member_item_id=MEMBER
    )
    record_case_verdict(test_db, requirement_id, "pass", evidence=False)

    status = _status(test_db, "run-red-no-evidence")

    assert status["outcome"] == OUTCOME_WAITING
    assert _kinds(status) == [FAILURE_PASSED_WITHOUT_EVIDENCE]
    assert status["case_failures"][0]["requirement_id"] == requirement_id
    assert any("no attached evidence" in r for r in status["reasons"])
