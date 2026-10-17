"""The deploy driver re-reads a read-only call that hit its read deadline.

A driver on an operator's laptop reaches the control plane over a slow link,
so one read can expire while the next one answers. Reads change nothing,
so the driver asks again a bounded number of times; a call that may write is
never resent, and a read that keeps expiring fails with the driver's own
recovery rather than the server's "narrow your read" hint.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import deploy_pipeline_control_plane as control_plane

RUN = "run-20260101-009"
QA_PENDING = "deployment_runs.execution.qa_pending"


def _expired(function_id: str = QA_PENDING) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=function_id,
        version="v1",
        result={},
        error=FunctionError(
            code=control_plane.READ_DEADLINE_CODE,
            message=f"{function_id} exceeded its 25s server read deadline.",
            recovery_hint="Retry a narrower read: name a project or section.",
        ),
    )


def _answered(result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function=QA_PENDING, version="v1", result=result
    )


@pytest.fixture
def sleeps(monkeypatch):
    waited: list[float] = []
    monkeypatch.setattr(control_plane.time, "sleep", waited.append)
    return waited


def test_an_expired_read_is_asked_again_until_it_answers(monkeypatch, sleeps, capsys):
    dispatch = Mock(
        side_effect=[_expired(), _answered({"unresolved": ["requirement #7"]})]
    )
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)

    assert control_plane.unresolved_qa(RUN) == ["requirement #7"]
    assert dispatch.call_count == 2
    assert sleeps == [control_plane._READ_DEADLINE_BACKOFF_SECONDS[0]]
    assert "exceeded its read deadline; reading again" in capsys.readouterr().err


def test_a_read_that_keeps_expiring_fails_with_the_driver_recovery(monkeypatch, sleeps):
    attempts = len(control_plane._READ_DEADLINE_BACKOFF_SECONDS) + 1
    dispatch = Mock(side_effect=[_expired() for _ in range(attempts)])
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)

    with pytest.raises(control_plane.DeploymentControlPlaneError) as raised:
        control_plane.unresolved_qa(RUN)

    assert dispatch.call_count == attempts
    assert sleeps == list(control_plane._READ_DEADLINE_BACKOFF_SECONDS)
    assert raised.value.code == control_plane.READ_DEADLINE_CODE
    message = str(raised.value)
    assert f"Every one of {attempts} attempts expired" in message
    assert f"yoke watch deploy -- {RUN}" in message
    assert "narrower read" not in message


def test_a_call_that_may_write_is_never_resent(monkeypatch, sleeps):
    function_id = "deployment_runs.execution.update"
    dispatch = Mock(return_value=_expired(function_id))
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)

    with pytest.raises(control_plane.DeploymentControlPlaneError):
        control_plane.update_run_field(RUN, "current_stage", "deploy")

    assert dispatch.call_count == 1
    assert sleeps == []


def test_other_refusals_are_not_retried(monkeypatch, sleeps):
    refusal = FunctionCallResponse(
        success=False,
        function=QA_PENDING,
        version="v1",
        result={},
        error=FunctionError(code="run_driver_mismatch", message="not your run"),
    )
    dispatch = Mock(return_value=refusal)
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)

    with pytest.raises(control_plane.DeploymentControlPlaneError, match="not your run"):
        control_plane.unresolved_qa(RUN)

    assert dispatch.call_count == 1
    assert sleeps == []
