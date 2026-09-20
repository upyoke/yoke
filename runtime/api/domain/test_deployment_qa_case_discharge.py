"""Discharging a stage obligation without a passing case of its own.

Two routes reach the same place: an operator waiver, and a corrected case
superseding a frozen broken one. Both let a stage subject through without
that case passing, and both must stay distinguishable from a subject that
actually passed.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
    seed_member_qa_case,
)
from yoke_core.domain.deployment_qa_stage_acceptance import (
    STAGE_ACCEPTED,
    STAGE_DISCHARGED,
    STAGE_NOT_RUN,
    stage_acceptance,
)
from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    deployment_qa_stage_subject,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_outcome import OUTCOME_DISCHARGED
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_requirement_ops import waive_requirement
from yoke_core.domain.qa_requirement_supersession import (
    QaSupersessionError,
    supersede_requirement,
    supersession_history,
)

STAGE = ITEM_QA_STAGE
MEMBER = 9801


def _seed(conn: Any, run_id: str) -> int:
    """Seed one member parked on the QA stage; return its case requirement."""
    return seed_member_qa_case(conn, run_id=run_id, member_item_id=MEMBER)


def _record_verdict(
    conn: Any, requirement_id: int, verdict: str, *, evidence: bool
) -> int:
    return record_case_verdict(conn, requirement_id, verdict, evidence=evidence)


def _execute_stage(
    conn: Any,
    run_id: str,
    verdicts: dict[int, str],
    *,
    evidence_for: set[int] | None = None,
) -> None:
    """Run the member's scoped execution, recording one verdict per case.

    ``evidence_for`` narrows which passing cases attach artifacts, standing
    in for a later execution that re-graded a case without re-capturing it.
    """
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=MEMBER,
        actor_id="2",
        session_id="member-qa",
    )
    for ordinal, entry in enumerate(execution["roster"]):
        requirement_id = int(entry["requirement_id"])
        verdict = verdicts[requirement_id]
        attaches = verdict == "pass" and (
            evidence_for is None or requirement_id in evidence_for
        )
        qa_run_id = _record_verdict(conn, requirement_id, verdict, evidence=attaches)
        advance_plan_execution(
            conn,
            execution,
            ordinal=ordinal,
            requirement_id=requirement_id,
            result={
                "requirement_id": requirement_id,
                "verdict": verdict,
                "case_outcome": "passed" if verdict == "pass" else "failed",
                "run_id": qa_run_id,
            },
        )
    finish_plan_execution(conn, execution, state="completed", reason="test-complete")
    conn.commit()


def _corrected_case(conn: Any, *, broken_id: int) -> int:
    """A second blocking case pinned to the same subject and target.

    Copies every column of the frozen row so the replacement carries a
    complete execution snapshot, exactly as a real corrected case does;
    only its key and position differ.
    """
    columns = [
        str(row[0])
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='qa_requirements' AND column_name<>'id' "
            "ORDER BY ordinal_position"
        ).fetchall()
    ]
    projected = [
        "%s" if column == "plan_case_key" else
        "case_position+1" if column == "case_position" else
        column
        for column in columns
    ]
    row = conn.execute(
        f"INSERT INTO qa_requirements({','.join(columns)}) "
        f"SELECT {','.join(projected)} FROM qa_requirements WHERE id=%s "
        "RETURNING id",
        ("command-smoke-corrected", int(broken_id)),
    ).fetchone()
    conn.commit()
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _status(conn: Any, run_id: str) -> dict[str, Any]:
    return deployment_qa_stage_status(
        conn, run_id=run_id, stage_name=STAGE, member_item_id=MEMBER
    )


def _acceptance(conn: Any, run_id: str):
    subject = deployment_qa_stage_subject(
        conn,
        run_id=run_id,
        stage_name=STAGE,
        member_item_id=MEMBER,
        require_active=False,
    )
    return stage_acceptance(
        conn,
        subject=subject,
        target=deployment_qa_execution_target(conn, subject),
        acceptance_qa_kind=DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    )


def test_unanswered_case_still_blocks_its_stage(test_db) -> None:
    run_id = "run-discharge-blocks"
    _seed(test_db, run_id)
    status = _status(test_db, run_id)
    assert not status["accepted"]
    assert any("no completed" in reason for reason in status["reasons"])
    assert _acceptance(test_db, run_id).state == STAGE_NOT_RUN


def test_waiving_every_case_discharges_the_member_without_an_execution(
    test_db,
) -> None:
    run_id = "run-discharge-waived"
    requirement_id = _seed(test_db, run_id)
    waive_requirement(
        test_db,
        requirement_id,
        "operator accepted the release without this case",
        source="operator",
        force=True,
    )
    status = _status(test_db, run_id)
    assert status["accepted"]
    # Distinguishable from a pass: the release contract keeps an authorized
    # discharge legible as one rather than laundering it into "passed".
    assert status["outcome"] == OUTCOME_DISCHARGED
    assert status["reasons"] == []
    acceptance = _acceptance(test_db, run_id)
    assert acceptance.state == STAGE_DISCHARGED
    assert acceptance.accepted
    assert acceptance.state != STAGE_ACCEPTED


def test_member_with_no_materialized_cases_is_not_discharged(test_db) -> None:
    run_id = "run-discharge-empty"
    requirement_id = _seed(test_db, run_id)
    test_db.execute("DELETE FROM qa_requirements WHERE id=%s", (requirement_id,))
    test_db.commit()
    status = _status(test_db, run_id)
    assert not status["accepted"]
    assert any("no concrete QA cases" in reason for reason in status["reasons"])


def test_corrected_case_supersedes_the_broken_one_without_a_waiver(test_db) -> None:
    run_id = "run-discharge-superseded"
    broken_id = _seed(test_db, run_id)
    corrected_id = _corrected_case(test_db, broken_id=broken_id)
    _execute_stage(test_db, run_id, {broken_id: "fail", corrected_id: "pass"})

    # The corrected case passing is not by itself enough: until the broken
    # case's obligation is discharged it still holds the whole stage, which
    # is the trap that left an operator waiver as the only exit.
    blocked = _status(test_db, run_id)
    assert not blocked["accepted"]
    assert any(f"#{broken_id}" in reason for reason in blocked["reasons"])

    supersede_requirement(
        test_db,
        requirement_id=broken_id,
        superseded_by_requirement_id=corrected_id,
        rationale="corrected case probes the field the command actually projects",
        source="agent",
    )

    # The broken row survives untouched as history, and never becomes a waiver.
    row = test_db.execute(
        "SELECT waived_at,superseded_by_requirement_id,supersession_rationale,"
        "supersession_source FROM qa_requirements WHERE id=%s",
        (broken_id,),
    ).fetchone()
    assert row["waived_at"] is None
    assert int(row["superseded_by_requirement_id"]) == corrected_id
    assert "corrected case probes" in str(row["supersession_rationale"])
    assert str(row["supersession_source"]) == "agent"

    history = supersession_history(test_db, run_id=run_id)
    assert [int(entry["id"]) for entry in history] == [broken_id]

    status = _status(test_db, run_id)
    assert status["accepted"], status["reasons"]


def test_supersession_refuses_a_replacement_that_did_not_pass(test_db) -> None:
    run_id = "run-discharge-unpassed"
    broken_id = _seed(test_db, run_id)
    corrected_id = _corrected_case(test_db, broken_id=broken_id)
    _record_verdict(test_db, corrected_id, "fail", evidence=False)
    with pytest.raises(QaSupersessionError) as excinfo:
        supersede_requirement(
            test_db,
            requirement_id=broken_id,
            superseded_by_requirement_id=corrected_id,
            rationale="hoping the replacement counts",
        )
    message = str(excinfo.value)
    assert "latest verdict is fail" in message
    assert f"yoke qa case run --requirement-id {corrected_id}" in message


def test_supersession_refuses_a_replacement_from_another_subject(test_db) -> None:
    run_id = "run-discharge-foreign"
    broken_id = _seed(test_db, run_id)
    corrected_id = _corrected_case(test_db, broken_id=broken_id)
    test_db.execute(
        "UPDATE qa_requirements SET deployment_member_item_id=%s WHERE id=%s",
        (MEMBER + 1, corrected_id),
    )
    _record_verdict(test_db, corrected_id, "pass", evidence=True)
    with pytest.raises(QaSupersessionError) as excinfo:
        supersede_requirement(
            test_db,
            requirement_id=broken_id,
            superseded_by_requirement_id=corrected_id,
            rationale="another member's passing case",
        )
    assert "deployment member differs" in str(excinfo.value)


def test_supersession_refuses_itself_and_an_empty_rationale(test_db) -> None:
    run_id = "run-discharge-self"
    broken_id = _seed(test_db, run_id)
    with pytest.raises(QaSupersessionError, match="cannot supersede itself"):
        supersede_requirement(
            test_db,
            requirement_id=broken_id,
            superseded_by_requirement_id=broken_id,
            rationale="circular",
        )
    with pytest.raises(QaSupersessionError, match="requires a rationale"):
        supersede_requirement(
            test_db,
            requirement_id=broken_id,
            superseded_by_requirement_id=broken_id + 1,
            rationale="   ",
        )


def test_corrected_case_evidence_counts_from_its_own_execution(test_db) -> None:
    """A corrected case usually runs under its own plan, so its own execution.

    Reading evidence only through the subject's newest execution made that
    passing case report "no attached evidence" and hold the stage it had
    just satisfied -- the supersession would name a row the gate still
    refused.
    """
    run_id = "run-discharge-second-execution"
    broken_id = _seed(test_db, run_id)
    corrected_id = _corrected_case(test_db, broken_id=broken_id)
    # The corrected case passes with evidence here...
    _execute_stage(test_db, run_id, {broken_id: "fail", corrected_id: "pass"})
    # ...and a later execution re-grades without capturing again, so the
    # subject's newest execution holds no evidence for it.
    _execute_stage(
        test_db,
        run_id,
        {broken_id: "fail", corrected_id: "pass"},
        evidence_for=set(),
    )

    supersede_requirement(
        test_db,
        requirement_id=broken_id,
        superseded_by_requirement_id=corrected_id,
        rationale="corrected case passed under its own execution",
    )
    status = _status(test_db, run_id)
    assert status["accepted"], status["reasons"]
