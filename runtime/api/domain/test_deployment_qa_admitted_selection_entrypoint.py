"""Ordinary client orchestration keeps the admitted selector through begin."""

from unittest.mock import patch

from runtime.api.domain.test_deployment_qa_admitted_plan_selection import (
    MEMBER,
    RUN,
    _seed,
)
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import qa_plan_execution
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    plan_execution_view,
)


def test_plan_run_materializes_then_begins_only_the_selected_frozen_plan(test_db):
    _, selected, _ = _seed(test_db)
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs["function_id"])
        payload = kwargs["payload"]
        assert payload["plan"] == str(selected)
        if kwargs["function_id"] == "qa.plan.materialize":
            receipt = materialize_deployment_qa_stage(
                test_db,
                deployment_run_id=RUN,
                deployment_stage="item-qa",
                deployment_member_item_id=MEMBER,
                agent_plan=payload["plan"],
            )
            assert receipt["created_requirement_ids"] == []
            return receipt
        assert kwargs["function_id"] == "qa.plan_execution.begin"
        execution = begin_plan_execution(
            test_db,
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            deployment_member_item_id=MEMBER,
            plan=payload["plan"],
            actor_id="2",
            session_id="ordinary-selected-entrypoint",
        )
        return plan_execution_view(test_db, execution)

    def run(**kwargs):
        roster = kwargs["execution"]["requirements"]
        assert {row["plan_id"] for row in roster} == {selected}
        assert len(roster) == 2
        return {"state": "waiting", "remaining_requirement_count": 0}

    with (
        patch.object(qa_plan_execution, "_call_plan_function", side_effect=dispatch),
        patch(
            "yoke_core.domain.qa_plan_execution_run.execute_begun_plan", side_effect=run
        ),
    ):
        result = qa_plan_execution.execute_plan(
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            deployment_member="member",
            plan=str(selected),
            project="yoke",
            actor=ActorContext(actor_id="2", session_id="ordinary-selected-entrypoint"),
        )
    assert result["state"] == "waiting"
    assert calls == ["qa.plan.materialize", "qa.plan_execution.begin"]
