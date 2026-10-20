"""A lost answer during scoped-QA dispatch is re-sent, then stops resumably.

The dispatch is idempotent -- it creates requirements only when absent and
keys its notices -- so a lost answer is sent again, up to three sends with
5s and 15s pauses. A refusal is never re-sent. Past the last send the outcome
is still unknown, so it is never read as a failed stage: the driver exits
without writing ``<stage>-failed`` or a run status, and the next re-drive
continues from the same stage.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from yoke_cli.transport.relay_telemetry import TRANSPORT_FAILED_CODE
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import deployment_qa_stage_dispatch as dispatch_mod
from yoke_core.domain.deploy_pipeline_unknown_outcome import (
    DeploymentOutcomeUnknown,
    preserve_unknown_outcome,
)
from yoke_core.domain.function_connection_loss import CONNECTION_LOST_CODE

_RUN = "run-20261019-007"


def _lost(code: str) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=dispatch_mod.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
        version="v1",
        request_id="req-lost-1",
        error=FunctionError(code=code, message="the connection is lost"),
    )


@pytest.fixture(autouse=True)
def _no_real_pauses(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("yoke_core.domain.deploy_pipeline_unknown_outcome.time.sleep", sleeps.append)
    return sleeps


def _dispatch(*responses: FunctionCallResponse) -> tuple[tuple[int, str], Mock]:
    sender = Mock(side_effect=list(responses))
    with patch(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        sender,
    ):
        result = dispatch_mod.dispatch_deployment_qa_stage(
            {"name": "item-qa", "scope": "item"}, run_id=_RUN
        )
    return result, sender


def _accepted() -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function=dispatch_mod.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
        version="v1",
        result={"code": -4, "message": "member pending"},
    )


@pytest.mark.parametrize("code", [CONNECTION_LOST_CODE, TRANSPORT_FAILED_CODE])
def test_a_loss_followed_by_success_makes_two_calls(code, _no_real_pauses):
    result, sender = _dispatch(_lost(code), _accepted())

    assert result == (-4, "member pending")
    assert sender.call_count == 2
    assert _no_real_pauses == [5.0]


@pytest.mark.parametrize("code", [CONNECTION_LOST_CODE, TRANSPORT_FAILED_CODE])
def test_three_losses_raise_after_three_calls(code, _no_real_pauses):
    sender = Mock(return_value=_lost(code))
    with patch(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        sender,
    ), pytest.raises(DeploymentOutcomeUnknown) as raised:
        dispatch_mod.dispatch_deployment_qa_stage(
            {"name": "item-qa", "scope": "item"}, run_id=_RUN
        )
    assert sender.call_count == 3
    assert _no_real_pauses == [5.0, 15.0]
    text = str(raised.value)
    assert dispatch_mod.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION in text
    assert "req-lost-1" in text
    assert _RUN in text


def test_the_driver_exits_without_recording_a_failure(capsys):
    failed = []

    @preserve_unknown_outcome
    def drive():
        (rc, diagnostic), _sender = _dispatch(*[_lost(CONNECTION_LOST_CODE)] * 3)
        failed.append((rc, diagnostic))  # the stage-failure path
        return rc

    assert drive() == 1
    assert failed == []
    err = capsys.readouterr().err
    assert "deployment_outcome_unknown" in err
    assert "No retry or failure transition was issued" in err


def test_a_genuine_refusal_still_fails_the_stage():
    refused = FunctionCallResponse(
        success=False,
        function=dispatch_mod.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
        version="v1",
        error=FunctionError(code="plan_execution_invalid", message="no stage"),
    )
    (code, diagnostic), sender = _dispatch(refused)
    assert code == 1
    assert "no stage" in diagnostic
    # A refusal is an answer: it is never sent again.
    assert sender.call_count == 1
