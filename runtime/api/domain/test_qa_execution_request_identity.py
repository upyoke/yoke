"""Continuation uses durable execution ownership while retaining scope checks."""

from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.domain.test_deployment_qa_takeover_identity import (
    _execution,
    _shared_execution,
)
from runtime.api.domain import test_deployment_run_target_takeover as takeover
from yoke_core.domain.qa_execution_request_identity import resolve_execution_request
from yoke_core.domain.function_target_resolution import resolve_project_context
from yoke_core.domain.handlers.qa_plan_execution import handle_plan_execution_heartbeat


def _request(execution, target=None):
    return FunctionCallRequest(
        function="qa.plan_execution.heartbeat",
        target=target or TargetRef(kind="global"),
        actor=ActorContext(
            actor_id=execution["actor_id"], session_id=execution["session_id"]
        ),
        payload={"execution_id": execution["id"]},
    )


def test_release_continuation_resolves_execution_and_retains_scope(
    test_db, monkeypatch
):
    execution = _execution(test_db, monkeypatch)
    test_db.commit()
    request = _request(execution)
    resolved = resolve_execution_request(test_db, request)
    assert resolved.target.deployment_run_id == takeover.NEW
    assert request.target.deployment_run_id is None
    assert resolve_project_context(
        test_db, SimpleNamespace(function_id=request.function), request
    ) == (1, "yoke")
    outcome = handle_plan_execution_heartbeat(request)
    assert outcome.primary_success, outcome.error
    for target, reason in (
        (
            TargetRef(kind="deployment_run", deployment_run_id=takeover.OLD),
            "release_selector_removed",
        ),
        (TargetRef(kind="item", item_id=takeover.WAITING), "item_mismatch"),
        (TargetRef(kind="global", project_id="missing-project"), "project_unknown"),
    ):
        with pytest.raises(ValueError, match=reason):
            resolve_execution_request(test_db, _request(execution, target))
    other = request.model_copy(
        update={
            "actor": ActorContext(
                actor_id=execution["actor_id"], session_id="another-owner"
            )
        }
    )
    assert not handle_plan_execution_heartbeat(other).primary_success


def test_shared_continuation_accepts_only_attaching_item(test_db, monkeypatch):
    from runtime.api.domain import test_deployment_qa_shared_plans as shared

    execution = _shared_execution(test_db, monkeypatch)
    for member in shared.MEMBERS:
        resolved = resolve_execution_request(
            test_db, _request(execution, TargetRef(kind="item", item_id=member))
        )
        assert resolved.target.deployment_run_id == takeover.NEW
    with pytest.raises(ValueError, match="item_mismatch"):
        resolve_execution_request(
            test_db, _request(execution, TargetRef(kind="item", item_id=-1))
        )


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("mission", [False, True])
def test_host_runner_admission_resolves_transferred_execution(
    test_db, monkeypatch, shared, mission
):
    from yoke_core.domain import machine_qa_plan_case_execution as runner

    execution = (_shared_execution if shared else _execution)(test_db, monkeypatch)
    requirement_id = execution["roster"][0]["requirement_id"]
    calls = []

    def dispatch(function_id, *, target, actor, payload, **kwargs):
        assert function_id == "test_machine.plan_case.begin"
        assert target.kind == "global"
        assert target.deployment_run_id is None
        assert payload == {
            "execution_id": execution["id"],
            "ordinal": 0,
            "requirement_id": requirement_id,
        }
        request = FunctionCallRequest(
            function=function_id, target=target, actor=actor, payload=payload
        )
        resolved = resolve_execution_request(test_db, request)
        assert resolved.target.deployment_run_id == takeover.NEW
        assert resolve_project_context(
            test_db, SimpleNamespace(function_id=function_id), request
        ) == (1, "yoke")
        calls.append(function_id)
        return {"state": "blocked", "result": {"requirement_id": requirement_id}}

    monkeypatch.setattr(runner, "_dispatch", dispatch)
    execute = (
        runner.execute_plan_agent_mission_case
        if mission else runner.execute_plan_machine_case
    )
    result = execute(
        {
            "requirement_id": requirement_id,
            "deployment_run_id": takeover.OLD,
            "project": "yoke",
        },
        execution_id=execution["id"],
        ordinal=0,
        actor=ActorContext(
            actor_id=execution["actor_id"], session_id=execution["session_id"]
        ),
    )
    assert result == {"requirement_id": requirement_id}
    assert calls == ["test_machine.plan_case.begin"]
