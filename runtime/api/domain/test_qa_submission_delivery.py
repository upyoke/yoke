"""Lost verdict replies recover exact requests without pausing saved evidence."""

import pytest

from runtime.api.domain.qa_plan_checkin_recovery_test_support import _response
from runtime.api.domain.qa_plan_execution_fail_closed_test_support import ACTOR
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.qa_plan_execution_checkin import deliver_plan_function
from yoke_core.domain.qa_plan_execution_reentry import pause_execution
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError


@pytest.mark.parametrize(
    "function", ["qa.plan_execution.complete", "qa.plan_review.submit"]
)
def test_lost_verdict_reply_replays_same_request(monkeypatch, function):
    calls = []

    def transport(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _response(kwargs, code="https_transport_failed")
        if len(calls) == 2:
            return _response(kwargs, code="idempotency_request_in_flight")
        return _response(kwargs, result={"state": "completed"})

    monkeypatch.setattr(
        "yoke_core.domain.qa_composed_dispatch.call_qa_function", transport
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_execution_checkin.time.sleep", lambda _: None
    )
    result = deliver_plan_function(
        function_id=function,
        target=TargetRef(kind="global"),
        payload={"execution_id": "saved"},
        actor=ACTOR,
    )
    assert result["state"] == "completed"
    assert calls[0] == calls[1] == calls[2]
    assert len(calls) == 3


def test_completed_execution_recovery_names_driver_without_reconcile():
    with pytest.raises(QaPlanExecutionStateError) as error:
        pause_execution(
            None,
            {"state": "completed", "deployment_run_id": "run-saved"},
            phase="checkin",
            cursor=0,
            request_id="saved",
            attempts=[],
        )
    assert "verdict is saved" in str(error.value)
    assert "yoke deployment-runs get run-saved" in str(error.value)
    assert "reconcile" not in str(error.value)
