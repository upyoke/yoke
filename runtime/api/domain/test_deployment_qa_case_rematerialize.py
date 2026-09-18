"""Refreshing an already-materialized deployment stage from its plan.

A materialized case is unique per subject and target, so a corrected plan
case cannot arrive as a second row. Refreshing in place is the way through,
and it stops at the line a run-bound case draws: a case that has answered is
an acceptance record, not a draft.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
    seed_member_qa_case,
)
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)

MEMBER = 9811


def _seed(conn, run_id: str) -> int:
    return seed_member_qa_case(conn, run_id=run_id, member_item_id=MEMBER)


def _record_verdict(conn, requirement_id: int, verdict: str, *, evidence: bool) -> int:
    return record_case_verdict(conn, requirement_id, verdict, evidence=evidence)


STAGE = ITEM_QA_STAGE


def test_rematerialize_refreshes_an_unanswered_deployment_case(test_db) -> None:
    run_id = "run-rematerialize-open"
    requirement_id = _seed(test_db, run_id)
    plan_id = int(
        test_db.execute(
            "SELECT plan_id FROM qa_requirements WHERE id=%s", (requirement_id,)
        ).fetchone()["plan_id"]
    )
    test_db.execute(
        "UPDATE qa_plan_cases SET instructions=%s WHERE plan_id=%s",
        ("run the corrected smoke command", plan_id),
    )
    test_db.commit()

    result = rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=MEMBER,
    )
    assert result["refreshed_requirement_ids"] == [requirement_id]
    row = test_db.execute(
        "SELECT instructions,execution_target_digest FROM qa_requirements "
        "WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    assert str(row["instructions"]) == "run the corrected smoke command"
    # The frozen run keeps the target its stage receipt pinned.
    assert str(row["execution_target_digest"])


def test_rematerialize_refuses_an_answered_deployment_case(test_db) -> None:
    run_id = "run-rematerialize-answered"
    requirement_id = _seed(test_db, run_id)
    _record_verdict(test_db, requirement_id, "fail", evidence=False)
    with pytest.raises(QaPlanError) as excinfo:
        rematerialize_for_deployment_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=STAGE,
            deployment_member_item_id=MEMBER,
        )
    message = str(excinfo.value)
    assert f"requirement #{requirement_id}" in message
    assert "already recorded fail" in message
    assert "yoke qa requirement supersede" in message


def test_rematerialize_refuses_a_subject_with_no_materialized_cases(test_db) -> None:
    run_id = "run-rematerialize-empty"
    requirement_id = _seed(test_db, run_id)
    test_db.execute("DELETE FROM qa_requirements WHERE id=%s", (requirement_id,))
    test_db.commit()
    with pytest.raises(QaPlanError, match="no materialized plan cases"):
        rematerialize_for_deployment_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=STAGE,
            deployment_member_item_id=MEMBER,
        )
