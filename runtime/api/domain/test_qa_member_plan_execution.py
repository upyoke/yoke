"""One CLI invocation freezes and runs one explicit QA partition."""

from unittest import mock


def test_scoped_client_executes_each_host_roster_under_its_own_plan_lease():
    from yoke_contracts.api.function_call import ActorContext
    from yoke_core.domain import qa_plan_execution

    machines = ("linux-lab", "test-mac")
    calls = []
    rosters = []
    for index, test_machine in enumerate(machines):
        rosters.append(
            {
                "execution_id": test_machine,
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
                        "case_key": test_machine,
                        "case_position": index + 1,
                        "baseline_position": 1,
                        "host_baseline": "fresh-host",
                        "starting_state": "baseline",
                        "runner_id": "host_control",
                        "method_config": {"os": ("linux", "macos")[index]},
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
        # Each roster's host comes from its own plan lease; no case names one.
        assert kwargs["execution_id"] == case["case_key"]
        assert "test_machine" not in kwargs
        return {"requirement_id": case["requirement_id"], "verdict": "pass"}

    results = []
    with (
        mock.patch.object(
            qa_plan_execution, "_call_plan_function", side_effect=dispatch
        ),
        mock.patch(
            "yoke_core.domain.machine_qa_plan_case_execution.execute_plan_machine_case",
            side_effect=run_case,
        ) as execute,
    ):
        for index in range(2):
            results.append(qa_plan_execution.execute_plan(
                deployment_run_id="run-hosts",
                deployment_stage="item-qa",
                deployment_member="member",
                project="project",
                partition=str(index) * 64,
                actor=ActorContext(actor_id="2", session_id=f"host-owner-{index}"),
            ))
            assert execute.call_count == index + 1
    assert [result["execution_id"] for result in results] == list(machines)
    assert all(result["state"] == "passed" for result in results)
    assert [
        call["payload"]["partition"]
        for call in calls if call["function_id"] == "qa.plan_execution.begin"
    ] == ["0" * 64, "1" * 64]
    assert execute.call_count == 2
    assert [
        call["payload"]["execution_id"]
        for call in calls
        if call["function_id"] == "qa.plan_execution.complete"
    ] == list(machines)
    for call in calls:
        fresh = call["function_id"] in {
            "qa.plan.materialize",
            "qa.plan_execution.begin",
        }
        assert call["target"].deployment_run_id == ("run-hosts" if fresh else None)
        assert call["target"].kind == ("deployment_run" if fresh else "global")
    assert all(
        call["payload"]["deployment_member"] == "member"
        for call in calls
        if call["function_id"] == "qa.plan_execution.begin"
    )
