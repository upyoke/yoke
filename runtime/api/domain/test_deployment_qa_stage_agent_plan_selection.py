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
from yoke_core.domain.qa_requirement_replacement import declare_replacements
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict

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


def test_failed_admitted_case_accepts_only_an_explicit_correction(test_db) -> None:
    item_id = 9725
    run_id = "run-admitted-case-correction"
    _member(
        test_db,
        run_id=run_id,
        item_id=item_id,
        sequence=725,
        method_id="browser-inspection",
    )
    initial = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=item_id,
    )
    failed_id = initial["created_requirement_ids"][0]
    record_case_verdict(test_db, failed_id, "fail", evidence=True)
    plan_id = _plan(test_db, "correct-ambiguous-selector")

    with pytest.raises(QaPlanError, match="exactly those corrected case keys"):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=STAGE,
            deployment_member_item_id=item_id,
            agent_plan=str(plan_id),
            replacement_keys={"wrong-key"},
        )

    corrected = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=item_id,
        agent_plan=str(plan_id),
        replacement_keys={"command-smoke"},
        commit=False,
    )
    # A corrected case inherits the frozen subject's target environment.
    test_db.execute(
        "UPDATE qa_requirements SET target_env=(SELECT target_env FROM qa_requirements WHERE id=%s) WHERE id=%s",
        (failed_id, corrected["created_requirement_ids"][0]),
    )
    declaration = declare_replacements(
        test_db,
        [{"case_key": "command-smoke", "requirement_id": failed_id}],
        materialized_requirement_ids=corrected["created_requirement_ids"],
    )
    test_db.commit()
    assert (
        declaration[0]["replacement_requirement_id"]
        == corrected["created_requirement_ids"][0]
    )
