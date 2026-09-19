"""--plan selects cases only for a deployment QA stage that names none.

A stage already carrying cases -- pinned, frozen, member-attached, admitted
from the member's own post-deploy obligations, or authored directly -- gains
nothing from an agent-selected plan: it materializes a SECOND set of
obligations beside the ones the stage credits, and then waits on both.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import _plan
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
    _seed_selected_requirement_run,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_management import QaPlanError

STAGE = "member-qa"


def _member(conn, *, run_id: str, item_id: int, sequence: int, method_id: str | None):
    insert_item(
        conn,
        id=item_id,
        project_sequence=sequence,
        workflow_id="issue",
        status="done",
    )
    requirement_id = _original_requirement(conn, item_id=item_id, method_id=method_id)
    _seed_selected_requirement_run(
        conn, run_id=run_id, item_id=item_id, requirement_id=requirement_id
    )


def test_a_stage_whose_member_admits_a_case_refuses_an_agent_selected_plan(
    test_db,
) -> None:
    item_id = 9721
    _member(
        test_db,
        run_id="run-plan-beside-admitted",
        item_id=item_id,
        sequence=721,
        method_id="browser-inspection",
    )
    plan_id = _plan(test_db, "duplicate-selection")

    with pytest.raises(QaPlanError, match="already names its cases"):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id="run-plan-beside-admitted",
            deployment_stage=STAGE,
            deployment_member_item_id=item_id,
            agent_plan=str(plan_id),
        )


def test_the_refusal_names_re_running_without_the_flag(test_db) -> None:
    item_id = 9722
    _member(
        test_db,
        run_id="run-plan-refusal-recovery",
        item_id=item_id,
        sequence=722,
        method_id="browser-inspection",
    )
    plan_id = _plan(test_db, "duplicate-selection-recovery")

    with pytest.raises(QaPlanError) as refusal:
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id="run-plan-refusal-recovery",
            deployment_stage=STAGE,
            deployment_member_item_id=item_id,
            agent_plan=str(plan_id),
        )

    assert "without --plan" in str(refusal.value)


def test_a_stage_that_names_no_cases_still_takes_the_agent_selected_plan(
    test_db,
) -> None:
    item_id = 9723
    _member(
        test_db,
        run_id="run-plan-fills-empty-stage",
        item_id=item_id,
        sequence=723,
        method_id=None,
    )
    plan_id = _plan(test_db, "empty-stage-selection")

    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-plan-fills-empty-stage",
        deployment_stage=STAGE,
        deployment_member_item_id=item_id,
        agent_plan=str(plan_id),
    )

    assert result["created_requirement_ids"]


def test_re_supplying_a_plan_stays_open_for_a_corrected_case(test_db) -> None:
    """The refusal targets a duplicate set, not the content-refresh repair."""
    item_id = 9724
    _member(
        test_db,
        run_id="run-plan-twice",
        item_id=item_id,
        sequence=724,
        method_id=None,
    )
    plan_id = _plan(test_db, "first-selection")
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-plan-twice",
        deployment_stage=STAGE,
        deployment_member_item_id=item_id,
        agent_plan=str(plan_id),
    )

    again = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-plan-twice",
        deployment_stage=STAGE,
        deployment_member_item_id=item_id,
        agent_plan=str(plan_id),
    )

    assert again["created_requirement_ids"] == []
