"""New plan admission fills only a deployment QA stage that names none.

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

    with pytest.raises(QaPlanError, match="plan_group_not_open"):
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

    assert "plan_group_not_open" in str(refusal.value)
    assert "yoke deployment-runs get" in str(refusal.value)








def test_an_agent_admission_does_not_leave_the_stage_open_for_unrelated_plans(test_db):
    """An agent selection freezes into the run, at a run-scoped stage."""
    import json

    from runtime.api.domain.test_deployment_qa_stage_execution import (
        _seed_run,
        _stages,
    )

    run_id = "run-agent-selection-closed"
    first = _plan(test_db, "initial-agent-plan")
    other = _plan(test_db, "unadmitted-extra-plan")
    stages = _stages(first)
    del stages[1]["cases"]
    stages[1].update(name="run-qa", scope="run")
    _seed_run(test_db, run_id=run_id, stages=stages, members=(9726,))
    subject = dict(deployment_run_id=run_id, deployment_stage="run-qa")

    def frozen():
        return test_db.execute(
            "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]

    admitted = materialize_deployment_qa_stage(
        test_db, **subject, agent_plan=str(first)
    )
    before = [
        tuple(row)
        for row in test_db.execute(
            "SELECT * FROM qa_requirements ORDER BY id"
        ).fetchall()
    ]
    selections = json.loads(frozen())["selections"]
    assert [s["plan"]["id"] for s in selections if s.get("selected_by_agent")] == [first]
    snapshot = frozen()
    with pytest.raises(QaPlanError, match="stage already names its cases"):
        materialize_deployment_qa_stage(test_db, **subject, agent_plan=str(other))
    assert [
        tuple(row)
        for row in test_db.execute(
            "SELECT * FROM qa_requirements ORDER BY id"
        ).fetchall()
    ] == before
    assert frozen() == snapshot
    selected = materialize_deployment_qa_stage(
        test_db, **subject, agent_plan=str(first)
    )
    assert selected["created_requirement_ids"] == []
    assert selected["existing_requirement_ids"] == admitted["created_requirement_ids"]
