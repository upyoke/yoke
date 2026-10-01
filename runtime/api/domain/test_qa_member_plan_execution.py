"""Scoped client orchestration stops on waits and continues completed hosts."""

from unittest import mock

import pytest

from yoke_core.domain.qa_member_plan_execution import execute_member_partitions
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError


def _result(execution_id, requirement_id, remaining, state="passed"):
    return {
        "execution_id": execution_id,
        "state": state,
        "remaining_requirement_count": remaining,
        "results": [{"requirement_id": requirement_id, "verdict": "pass"}],
        "requirement_count": 1,
        "executed_count": 1,
    }


def test_completed_hosts_continue_with_same_scope_and_aggregate_results():
    runner = mock.Mock(side_effect=[_result("linux", 10, 1), _result("mac", 11, 0)])
    result = execute_member_partitions(runner)(
        deployment_run_id="run-hosts",
        deployment_stage="item-qa",
        deployment_member="member",
        project="project",
        continue_mission=True,
    )
    assert result["execution_ids"] == ["linux", "mac"]
    assert result["requirement_count"] == result["executed_count"] == 2
    assert [row["requirement_id"] for row in result["results"]] == [10, 11]
    first, second = (call.kwargs for call in runner.call_args_list)
    assert first == {**second, "continue_mission": True}
    assert second["continue_mission"] is False


@pytest.mark.parametrize(
    "state", ["waiting", "awaiting_agent_review", "failed", "error"]
)
def test_unsettled_host_stops_before_another_execution(state):
    runner = mock.Mock(return_value=_result("linux", 10, 1, state))
    result = execute_member_partitions(runner)(
        deployment_stage="item-qa", deployment_member="member"
    )
    runner.assert_called_once()
    assert result["state"] == state and result["remaining_requirement_count"] == 1


def test_old_server_response_keeps_single_execution_semantics():
    runner = mock.Mock(
        return_value={
            "execution_id": "single",
            "state": "passed",
            "results": [],
            "requirement_count": 2,
            "executed_count": 2,
        }
    )
    result = execute_member_partitions(runner)(
        deployment_stage="item-qa", deployment_member="member"
    )
    runner.assert_called_once()
    assert result["state"] == "passed"


def test_a_repeated_completed_execution_refuses_with_recovery():
    runner = mock.Mock(return_value=_result("same", 10, 1))
    with pytest.raises(
        QaPlanExecutionError, match="member_machine_partition_stalled.*report"
    ):
        execute_member_partitions(runner)(
            deployment_stage="item-qa", deployment_member="member"
        )


def test_scoped_client_executes_each_host_roster_under_its_own_plan_lease():
    from yoke_contracts.api.function_call import ActorContext
    from yoke_core.domain import qa_plan_execution

    machines = ("linux-lab", "test-mac")
    calls = []
    rosters = []
    for index, machine in enumerate(machines):
        rosters.append(
            {
                "execution_id": machine,
                "state": "active",
                "cursor_ordinal": 0,
                "remaining_requirement_count": 1 - index,
                "results": [],
                "deployment_run_id": "run-hosts",
                "deployment_stage": "item-qa",
                "deployment_member_item_id": 42,
                "execution_target": {
                    "environment": {"name": "production"},
                    "endpoints": {},
                },
                "requirements": [
                    {
                        "requirement_id": 10 + index,
                        "plan_id": 1,
                        "case_key": machine,
                        "case_position": index + 1,
                        "baseline_position": 1,
                        "host_baseline": "fresh-host",
                        "runner_id": "host_control",
                        "required_capability_kinds": [f"test-machine:{machine}"],
                    }
                ],
            }
        )
    pending = iter(rosters)

    def dispatch(**kwargs):
        calls.append(kwargs)
        return (
            next(pending) if kwargs["function_id"] == "qa.plan_execution.begin" else {}
        )

    def run_case(case, **kwargs):
        assert kwargs["execution_id"] == kwargs["machine"] == case["case_key"]
        return {"requirement_id": case["requirement_id"], "verdict": "pass"}

    with (
        mock.patch.object(
            qa_plan_execution, "_call_plan_function", side_effect=dispatch
        ),
        mock.patch(
            "yoke_core.domain.machine_qa_plan_case_execution.execute_plan_machine_case",
            side_effect=run_case,
        ) as execute,
        mock.patch(
            "yoke_core.domain.machine_qa_case_execution.execute_materialized_machine_baseline_group"
        ) as group,
    ):
        result = qa_plan_execution.execute_plan(
            deployment_run_id="run-hosts",
            deployment_stage="item-qa",
            deployment_member="member",
            project="project",
            actor=ActorContext(actor_id="2", session_id="host-owner"),
        )
    assert result["state"] == "passed" and result["execution_ids"] == list(machines)
    assert execute.call_count == 2
    group.assert_not_called()
    assert [
        call["payload"]["execution_id"]
        for call in calls
        if call["function_id"] == "qa.plan_execution.complete"
    ] == list(machines)
    assert all(call["target"].deployment_run_id == "run-hosts" for call in calls)
    assert all(
        call["payload"]["deployment_member"] == "member"
        for call in calls
        if call["function_id"] == "qa.plan_execution.begin"
    )
