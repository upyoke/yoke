"""Client dispatch and authorization coverage for deployment-run QA."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from runtime.api.domain.deployment_run_qa_plan_execution_test_support import (
    RUN_ID,
    deployment_run,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import qa_case_execution, qa_plan_execution
from yoke_core.domain.function_target_resolution import resolve_project_context


def test_client_materializes_before_server_authorized_run_execution() -> None:
    actor = ActorContext(actor_id="7", session_id="deployment-client")
    calls: list[tuple[str, TargetRef, dict]] = []

    def dispatch(**kwargs):
        calls.append(
            (
                kwargs["function_id"],
                kwargs["target"],
                kwargs["payload"],
            )
        )
        if kwargs["function_id"] == "qa.plan_execution.begin":
            return {
                "execution_id": "deployment-execution",
                "item_id": None,
                "deployment_run_id": RUN_ID,
                "transition_id": None,
                "state": "active",
                "roster_digest": "digest",
                "cursor_ordinal": 0,
                "requirements": [
                    {
                        "requirement_id": 71,
                        "item_id": None,
                        "deployment_run_id": RUN_ID,
                        "plan_id": 9,
                        "case_key": "release-command",
                        "case_position": 1,
                        "baseline_position": 1,
                        "host_baseline": None,
                        "executor_id": "worktree_run",
                    }
                ],
                "results": [],
            }
        return {}

    with (
        mock.patch.object(
            qa_plan_execution,
            "_call_plan_function",
            side_effect=dispatch,
        ),
        mock.patch.object(
            qa_case_execution,
            "execute_case_context",
            return_value={
                "requirement_id": 71,
                "executor_id": "worktree_run",
                "verdict": "pass",
                "case_outcome": "passed",
            },
        ),
    ):
        result = qa_plan_execution.execute_plan(
            deployment_run_id=RUN_ID,
            plan="deployment-smoke",
            project="yoke",
            actor=actor,
        )

    assert result["state"] == "passed"
    assert result["deployment_run_id"] == RUN_ID
    assert [function for function, _target, _payload in calls] == [
        "qa.plan.materialize",
        "qa.plan_execution.begin",
        "qa.plan_execution.heartbeat",
        "qa.plan_execution.advance",
        "qa.plan_execution.complete",
    ]
    assert all(target.kind == "deployment_run" for _, target, _ in calls)
    assert calls[0][2] == {
        "plan": "deployment-smoke",
        "project": "yoke",
    }


def test_deployment_run_project_hint_must_match_row_authority() -> None:
    with test_database() as conn:
        deployment_run(conn)
        entry = SimpleNamespace(function_id="qa.plan_execution.begin")
        matching = FunctionCallRequest(
            function="qa.plan_execution.begin",
            actor=ActorContext(actor_id="7", session_id="deployment-authz"),
            target=TargetRef(
                kind="deployment_run",
                deployment_run_id=RUN_ID,
                project_id="yoke",
            ),
        )
        mismatched = matching.model_copy(
            update={
                "target": TargetRef(
                    kind="deployment_run",
                    deployment_run_id=RUN_ID,
                    project_id="externalwebapp",
                )
            }
        )
        assert resolve_project_context(conn, entry, matching) == (1, "yoke")
        assert resolve_project_context(conn, entry, mismatched) is None
