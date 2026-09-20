"""Empty QA plan roster: discharged without cases vs never asked."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from yoke_core.domain.post_deploy_verification_answer import NO_OBLIGATION_QA_KIND
from yoke_core.domain.qa_plan_empty_roster import (
    DISCHARGED_BEGIN_CODE,
    DISCHARGED_PLAN_STATE,
    QaPlanRosterDischarged,
    as_discharged_plan_result,
    discharged_without_cases_statement,
)
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
from yoke_core.domain.qa_plan_execution_roster import ordered_plan_requirements

LINEAGE = "f" * 40
DISCHARGED_ITEM = 9841
UNANSWERED_ITEM = 9842


def _member_on_qa_stage(conn, *, run_id: str, item_id: int) -> None:
    seed_run_standing_on_qa_stage(
        conn,
        run_id=run_id,
        project="yoke",
        stages=item_qa_stage_definitions(None),
        members=(item_id,),
        lineage=LINEAGE,
    )


def _no_obligation_row(conn, item_id: int, reason: str) -> int:
    requirement_id = int(
        conn.execute(
            "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,blocking_mode,"
            "requirement_source,instructions,workflow_transition_id,created_at) "
            "VALUES (%s,%s,'post_deploy','non_blocking','explicit',%s,'release',"
            "'2026-09-20T00:00:00Z') RETURNING id",
            (int(item_id), NO_OBLIGATION_QA_KIND, reason),
        ).fetchone()[0]
    )
    conn.commit()
    return requirement_id


def _roster(conn, *, run_id: str, item_id: int):
    return ordered_plan_requirements(
        conn,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=item_id,
    )


def test_empty_roster_distinguishes_discharge_from_never_asked(test_db) -> None:
    discharged_run = "run-empty-roster-discharged"
    unanswered_run = "run-empty-roster-unanswered"
    _member_on_qa_stage(test_db, run_id=discharged_run, item_id=DISCHARGED_ITEM)
    _member_on_qa_stage(test_db, run_id=unanswered_run, item_id=UNANSWERED_ITEM)
    requirement_id = _no_obligation_row(
        test_db, DISCHARGED_ITEM, "no runtime surface to observe"
    )

    with pytest.raises(QaPlanRosterDischarged) as discharged:
        _roster(test_db, run_id=discharged_run, item_id=DISCHARGED_ITEM)
    with pytest.raises(QaPlanExecutionError) as unanswered:
        _roster(test_db, run_id=unanswered_run, item_id=UNANSWERED_ITEM)

    discharged_message = str(discharged.value)
    unanswered_message = str(unanswered.value)

    assert discharged_message != unanswered_message
    assert f"#{requirement_id}" in discharged_message
    assert NO_OBLIGATION_QA_KIND in discharged_message
    assert "already satisfied" in discharged_message
    assert "Steering re-drives" in discharged_message
    assert "has no materialized QA cases" not in discharged_message
    assert "has no materialized QA cases" in unanswered_message
    assert "item-plan attach" in unanswered_message
    assert "record-no-obligation" in unanswered_message
    assert isinstance(unanswered.value, QaPlanExecutionError)
    assert not isinstance(unanswered.value, QaPlanRosterDischarged)


def test_a_discharged_begin_refusal_is_a_successful_plan_result() -> None:
    statement = discharged_without_cases_statement(
        requirement_id=17, qa_kind=NO_OBLIGATION_QA_KIND
    )
    result = as_discharged_plan_result(
        QaPlanExecutionError(
            f"qa.plan_execution.begin failed ({DISCHARGED_BEGIN_CODE}): "
            f"{statement}"
        )
    )

    assert result is not None
    assert result["state"] == DISCHARGED_PLAN_STATE
    assert result["message"] == statement
    assert result["requirements"] == []
    assert as_discharged_plan_result(
        QaPlanExecutionError("qa.plan_execution.begin failed (other): miss")
    ) is None
