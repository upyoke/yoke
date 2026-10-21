"""A waiver during a live walk records the case beside it; refusals keep their reason."""

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
    materialize_installer_campaign,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.qa_plan_execution_test_support import TEST_ITEM_REF
from runtime.api.domain.test_machine_qa_plan_execution import ACTOR, _request
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import (
    machine_qa_plan_case_execution as runner,
    qa_composed_dispatch,
)
from yoke_core.domain.handlers.machine_qa_plan_case import (
    handle_plan_case_begin,
    handle_plan_case_submit,
)
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_requirement_ops import waive_requirement

ITEM_ID = 4571


def _response(kwargs, *, result=None, error=None):
    return FunctionCallResponse(
        version="v1",
        function=kwargs["function_id"],
        request_id=kwargs["request_id"],
        success=error is None,
        result=result or {},
        error=error,
    )


def _walk(test_db, tmp_path, monkeypatch):
    materialize_installer_campaign(test_db, item_id=ITEM_ID)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution = begin_plan_execution(
        test_db,
        item_id=ITEM_ID,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_host_control.register_test_machine_host_control",
        lambda: None,
    )
    monkeypatch.setattr(
        runner, "refreshed_case_contract", lambda contract, **_: contract
    )
    return str(execution["id"]), execution["roster"][0]


def _waive(test_db, requirement_id):
    waive_requirement(
        test_db,
        requirement_id,
        "operator waived the case while the walk ran it",
        source="operator",
        force=True,
    )


def _run(case, execution_id):
    register_host_control_factory(lambda _: FakeHostControl())
    try:
        return runner.execute_plan_machine_case(
            {**case, "public_ref": TEST_ITEM_REF},
            execution_id=execution_id,
            ordinal=0,
            actor=ACTOR,
        )
    finally:
        clear_host_control_factory()


@pytest.mark.parametrize("waived_when", ["before_begin", "while_running"])
def test_a_case_waived_during_the_walk_records_its_result_and_the_walk_proceeds(
    test_db, tmp_path, monkeypatch, waived_when
):
    execution_id, case = _walk(test_db, tmp_path, monkeypatch)
    requirement_id = int(case["requirement_id"])
    if waived_when == "before_begin":
        _waive(test_db, requirement_id)

    def transport(**kwargs):
        function = kwargs["function_id"]
        if function == "qa.plan_execution.heartbeat":
            return _response(kwargs)
        request = _request(
            function,
            item_id=ITEM_ID,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
            payload=kwargs["payload"],
        )
        if function == "test_machine.plan_case.begin":
            response = handle_plan_case_begin(request)
            if waived_when == "while_running":
                _waive(test_db, requirement_id)
        else:
            assert function == "test_machine.plan_case.submit"
            response = handle_plan_case_submit(request)
        assert response.primary_success, response.error
        return _response(kwargs, result=response.result_payload)

    monkeypatch.setattr(qa_composed_dispatch, "call_qa_function", transport)

    result = _run(case, execution_id)

    assert result["requirement_id"] == requirement_id
    assert result["case_outcome"] == "passed"
    assert lock_plan_execution(test_db, execution_id)["cursor_ordinal"] == 1
    row = test_db.execute(
        "SELECT q.waived_at, COUNT(r.id) AS runs FROM qa_requirements q "
        "LEFT JOIN qa_runs r ON r.qa_requirement_id=q.id WHERE q.id=%s "
        "GROUP BY q.waived_at",
        (requirement_id,),
    ).fetchone()
    assert row["waived_at"] is not None
    assert row["runs"] == 1


def test_a_refused_submit_reports_the_servers_reason(test_db, tmp_path, monkeypatch):
    execution_id, case = _walk(test_db, tmp_path, monkeypatch)
    requirement_id = int(case["requirement_id"])
    refusal = f"materialized QA case requirement {requirement_id} not found"

    def transport(**kwargs):
        function = kwargs["function_id"]
        if function == "qa.plan_execution.heartbeat":
            return _response(kwargs)
        if function == "test_machine.plan_case.submit":
            return _response(
                kwargs,
                error=FunctionError(
                    code="test_machine_plan_case_submit_failed", message=refusal
                ),
            )
        request = _request(
            function,
            item_id=ITEM_ID,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
            payload=kwargs["payload"],
        )
        response = handle_plan_case_begin(request)
        assert response.primary_success, response.error
        return _response(kwargs, result=response.result_payload)

    monkeypatch.setattr(qa_composed_dispatch, "call_qa_function", transport)

    with pytest.raises(runner.MachinePlanCaseDispatchError) as caught:
        _run(case, execution_id)

    message = str(caught.value)
    assert "test_machine.plan_case.submit failed" in message
    assert "test_machine_plan_case_submit_failed" in message
    assert refusal in message
    assert "error_type=MachinePlanCaseDispatchError" not in message
