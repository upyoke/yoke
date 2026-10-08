"""Declared replacement retires predecessor grading immediately.

Only the final corrected case is graded while its actual passing verdict may
also record automatic predecessor supersession for audit.
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
from runtime.api.domain.test_deployment_run_auto_completion import _held_lock
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from yoke_core.domain.db_helpers import iso8601_now
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
    declare_existing_replacement,
)
from yoke_core.domain.qa_run_verdict_record import insert_qa_run

MEMBER = 9811


def _pass(conn: Any, run_id: str) -> list[int]:
    """Execute the member's roster to a pass; return the rows it discharged."""
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
    finish_plan_execution(conn, execution, state="completed", reason="test-complete")
    conn.commit()
    return [
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM qa_requirements WHERE superseded_by_requirement_id = ANY(%s) "
            "ORDER BY id",
            (passed,),
        ).fetchall()
    ]


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


def _failed_with_correction(
    conn: Any, run_id: str, verdict: str = "fail"
) -> tuple[int, int]:
    failed_id = seed_member_qa_case(conn, run_id=run_id, member_item_id=MEMBER)
    record_case_verdict(conn, failed_id, verdict, evidence=True)
    corrected_id = corrected_case(conn, failed_id=failed_id, case_key="smoke-fixed")
    declare(conn, failed_id, "smoke-fixed", [corrected_id])
    return failed_id, corrected_id


def test_declared_case_leaves_grading_to_its_pending_successor(test_db) -> None:
    run_id = "run-replacement-declared"
    failed_id, corrected_id = _failed_with_correction(test_db, run_id)

    assert (
        requirement_row(test_db, failed_id)["replacement_requirement_id"]
        == corrected_id
    )
    assert _roster(test_db, run_id) == [corrected_id]
    status = _status(test_db, run_id)
    assert not status["accepted"]
    assert any(f"#{corrected_id}" in reason for reason in status["reasons"]), status[
        "reasons"
    ]


@pytest.mark.parametrize("verdict", ["fail", "error"])
def test_passing_replacement_supersedes_the_failed_case(test_db, verdict) -> None:
    run_id = "run-replacement-pass"
    failed_id, corrected_id = _failed_with_correction(test_db, run_id, verdict)

    row = requirement_row(test_db, failed_id)
    assert row["replacement_requirement_id"] == corrected_id
    assert row["superseded_by_requirement_id"] is None
    assert not _status(test_db, run_id)["accepted"]

    assert _pass(test_db, run_id) == [failed_id]
    row = requirement_row(test_db, failed_id)
    assert row["superseded_by_requirement_id"] == corrected_id
    assert row["supersession_source"] == "agent"
    assert f"requirement {corrected_id}" in row["supersession_rationale"]
    assert row["waived_at"] is None
    assert _roster(test_db, run_id) == [corrected_id]
    status = _status(test_db, run_id)
    assert status["accepted"], status["reasons"]


def test_failing_replacement_grades_only_the_successor(test_db) -> None:
    run_id = "run-replacement-fail"
    failed_id, corrected_id = _failed_with_correction(test_db, run_id)

    record_case_verdict(test_db, corrected_id, "fail", evidence=True)

    row = requirement_row(test_db, failed_id)
    assert row["superseded_by_requirement_id"] is None
    assert row["replacement_requirement_id"] == corrected_id
    status = _status(test_db, run_id)
    assert not status["accepted"]
    assert not any(
        f"requirement #{failed_id} " in reason for reason in status["reasons"]
    )
    assert any(f"#{corrected_id}" in reason for reason in status["reasons"])


def test_retry_correction_inherits_every_earlier_attempt(test_db) -> None:
    run_id = "run-replacement-retry"
    failed_id, first_fix = _failed_with_correction(test_db, run_id)
    record_case_verdict(test_db, first_fix, "fail", evidence=True)
    second_fix = corrected_case(test_db, failed_id=first_fix, case_key="smoke-fixed-2")

    declare(test_db, first_fix, "smoke-fixed-2", [second_fix])

    assert (
        requirement_row(test_db, failed_id)["replacement_requirement_id"] == second_fix
    )
    assert (
        requirement_row(test_db, first_fix)["replacement_requirement_id"] == second_fix
    )
    assert _roster(test_db, run_id) == [second_fix]

    assert _pass(test_db, run_id) == sorted([failed_id, first_fix])
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

    assert (
        requirement_row(test_db, failed_id)["replacement_requirement_id"]
        == refreshed_id
    )
    assert _roster(test_db, run_id) == [refreshed_id]


@pytest.mark.parametrize("verdict", ["fail", "error"])
def test_existing_corrected_case_replaces_failed_capture_with_sibling_pending(
    test_db, monkeypatch, verdict
) -> None:
    _isolate_status_effects(monkeypatch)
    _held_lock(monkeypatch)
    run_id = "run-direct-correction-and-sibling"
    failed_id = seed_member_qa_case(test_db, run_id=run_id, member_item_id=MEMBER)
    record_case_verdict(test_db, failed_id, verdict, evidence=True)
    corrected_id = corrected_case(
        test_db, failed_id=failed_id, case_key="selector-scoped"
    )
    sibling_id = corrected_case(test_db, failed_id=failed_id, case_key="other-check")

    declared = declare_existing_replacement(
        test_db, failed_id=failed_id, replacement_id=corrected_id
    )
    test_db.commit()
    assert (
        declare_existing_replacement(
            test_db, failed_id=failed_id, replacement_id=corrected_id
        )
        == declared
    )
    assert failed_id not in _roster(test_db, run_id)
    assert set(_roster(test_db, run_id)) == {corrected_id, sibling_id}
    assert requirement_row(test_db, failed_id)["superseded_by_requirement_id"] is None
    assert not _status(test_db, run_id)["accepted"]

    record_case_verdict(test_db, corrected_id, "pass", evidence=True)
    assert (
        requirement_row(test_db, failed_id)["superseded_by_requirement_id"]
        == corrected_id
    )
    assert not _status(test_db, run_id)["accepted"]

    _pass(test_db, run_id)
    run = test_db.execute(
        "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    assert run["status"] == "succeeded"


@pytest.mark.parametrize("verdict", [None, "pass", "undetermined"])
@pytest.mark.parametrize("declaration", ["existing", "materialized"])
def test_deployment_replacement_requires_fail_or_error_verdict(
    test_db, verdict, declaration
) -> None:
    run_id = "run-replacement-verdict-refusal"
    failed_id = seed_member_qa_case(test_db, run_id=run_id, member_item_id=MEMBER)
    if verdict is not None:
        insert_qa_run(
            test_db,
            qa_requirement_id=failed_id,
            performed_by="worktree_run",
            qa_kind="plan_case",
            verdict=verdict,
            verdict_reason="Capture could not be judged"
            if verdict == "undetermined"
            else None,
            started_at=iso8601_now(),
            completed_at=iso8601_now(),
            created_at=iso8601_now(),
        )
        test_db.commit()
    corrected_id = corrected_case(test_db, failed_id=failed_id, case_key="smoke-fixed")
    reason = (
        "already passed"
        if verdict == "pass" and declaration == "materialized"
        else "no fail or error verdict"
    )

    with pytest.raises(QaReplacementError, match=reason):
        if declaration == "existing":
            declare_existing_replacement(
                test_db, failed_id=failed_id, replacement_id=corrected_id
            )
        else:
            declare(test_db, failed_id, "smoke-fixed", [corrected_id])
    test_db.rollback()
    row = requirement_row(test_db, failed_id)
    assert row["replacement_requirement_id"] is None
    assert row["superseded_by_requirement_id"] is None
    assert set(_roster(test_db, run_id)) == {failed_id, corrected_id}
