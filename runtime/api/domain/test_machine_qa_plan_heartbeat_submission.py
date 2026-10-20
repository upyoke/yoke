"""A restore heartbeat loss cannot discard a finished machine case result."""

from contextlib import contextmanager
import json
from pathlib import Path

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
    materialize_installer_campaign,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.qa_plan_execution_test_support import TEST_ITEM_REF
from runtime.api.domain.test_machine_qa_plan_execution import ACTOR, _request
from runtime.api.domain.test_qa_plan_checkin_recovery import _response
from yoke_core.domain import (
    machine_qa_local_execution as local,
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
from yoke_core.domain.machine_qa_phase_heartbeat import heartbeat_during
from yoke_core.domain.qa_plan_execution_checkin import communication_unknown
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)


@pytest.mark.parametrize("submission_unreachable", [False, True])
def test_restore_heartbeat_loss_submits_result_or_preserves_unknown_payload(
    test_db, tmp_path, monkeypatch, capsys, submission_unreachable
):
    item_id = 4570
    materialize_installer_campaign(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    execution_id = str(execution["id"])
    case = execution["roster"][0]
    requirement_id = int(case["requirement_id"])
    restoring = False
    submitted = []
    lost_heartbeats = []

    @contextmanager
    def phase_heartbeat(phase, callback, **kwargs):
        nonlocal restoring
        restoring = phase == "starting_state_restore"
        try:
            with heartbeat_during(phase, callback, **kwargs):
                yield
        finally:
            restoring = False

    def transport(**kwargs):
        function = kwargs["function_id"]
        if function == "qa.plan_execution.heartbeat":
            if restoring:
                lost_heartbeats.append(kwargs["request_id"])
                return _response(kwargs, code="https_transport_failed")
            return _response(kwargs)
        request = _request(
            function,
            item_id=item_id,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
            payload=kwargs["payload"],
        )
        if function == "test_machine.plan_case.begin":
            response = handle_plan_case_begin(request)
        else:
            assert function == "test_machine.plan_case.submit"
            submitted.append(kwargs)
            if submission_unreachable:
                return _response(kwargs, code="https_transport_failed")
            response = handle_plan_case_submit(request)
        assert response.primary_success, response.error
        return _response(kwargs, result=response.result_payload)

    monkeypatch.setattr(qa_composed_dispatch, "call_qa_function", transport)
    monkeypatch.setattr(local, "heartbeat_during", phase_heartbeat)
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_execution_checkin.time.sleep", lambda _: None
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_host_control.register_test_machine_host_control",
        lambda: None,
    )
    monkeypatch.setattr(
        runner, "refreshed_case_contract", lambda contract, **_: contract
    )
    control = FakeHostControl()
    register_host_control_factory(lambda _: control)
    try:
        if submission_unreachable:
            with pytest.raises(runner.MachinePlanCaseDispatchError) as caught:
                runner.execute_plan_machine_case(
                    {**case, "public_ref": TEST_ITEM_REF},
                    execution_id=execution_id,
                    ordinal=0,
                    actor=ACTOR,
                )
            unknown = communication_unknown(caught.value)
            assert unknown is not None
            assert unknown.function_id == "test_machine.plan_case.submit"
            assert unknown.request_id == submitted[0]["request_id"]
            assert "qa_communication_outcome_unknown" in str(unknown)
            saved = json.loads(Path(unknown.evidence_path).read_text())["response"]
            assert saved["payload"] == submitted[0]["payload"]
            assert saved["request_id"] == unknown.request_id
        else:
            result = runner.execute_plan_machine_case(
                {**case, "public_ref": TEST_ITEM_REF},
                execution_id=execution_id,
                ordinal=0,
                actor=ACTOR,
            )
            assert result["requirement_id"] == requirement_id
            assert result["case_outcome"] == "passed"
    finally:
        clear_host_control_factory()

    assert len(submitted) == 1
    row = submitted[0]["payload"]["results"][0]
    assert row["case_outcome"] == "passed"
    assert row["evidence"]["starting_state_restore"]["restored"]
    assert lost_heartbeats
    assert len(set(lost_heartbeats)) == 1
    assert lock_plan_execution(test_db, execution_id)["cursor_ordinal"] == (
        0 if submission_unreachable else 1
    )
    capture = capsys.readouterr().out
    assert "qa_communication_outcome_unknown" in capture
    assert lost_heartbeats[0] in capture
