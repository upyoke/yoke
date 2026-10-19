"""A lost answer during scoped-QA dispatch stops the driver resumably.

The dispatch may or may not have changed state, so it is never read as a
failed stage: the driver exits without writing ``<stage>-failed`` or a run
status, and the next re-drive continues from the same stage.
"""

from __future__ import annotations

from unittest.mock import patch

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


def _dispatch(response: FunctionCallResponse):
    with patch(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        return_value=response,
    ):
        return dispatch_mod.dispatch_deployment_qa_stage(
            {"name": "item-qa", "scope": "item"}, run_id=_RUN
        )


@pytest.mark.parametrize("code", [CONNECTION_LOST_CODE, TRANSPORT_FAILED_CODE])
def test_a_lost_answer_is_an_unknown_outcome_not_a_failed_stage(code):
    with pytest.raises(DeploymentOutcomeUnknown) as raised:
        _dispatch(_lost(code))
    text = str(raised.value)
    assert dispatch_mod.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION in text
    assert "req-lost-1" in text
    assert _RUN in text


def test_the_driver_exits_without_recording_a_failure(capsys):
    failed = []

    @preserve_unknown_outcome
    def drive():
        rc, diagnostic = _dispatch(_lost(CONNECTION_LOST_CODE))
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
    code, diagnostic = _dispatch(refused)
    assert code == 1
    assert "no stage" in diagnostic
