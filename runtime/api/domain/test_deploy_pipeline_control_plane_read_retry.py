"""Deploy reads retry deadlines and connection failures on one bounded schedule.

Writes never use the read retry schedule. Exhausted reads distinguish their
failure and teach the same-run driver recovery.
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
    assert sleeps == [control_plane._READ_RETRY_BACKOFF_SECONDS[0]]
    assert "answered read_deadline_exceeded; reading again" in capsys.readouterr().err


def test_a_read_that_keeps_expiring_fails_with_the_driver_recovery(monkeypatch, sleeps):
    attempts = len(control_plane._READ_RETRY_BACKOFF_SECONDS) + 1
    dispatch = Mock(side_effect=[_expired() for _ in range(attempts)])
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)

    with pytest.raises(control_plane.DeploymentControlPlaneError) as raised:
        control_plane.unresolved_qa(RUN)

    assert dispatch.call_count == attempts
    assert sleeps == list(control_plane._READ_RETRY_BACKOFF_SECONDS)
    assert raised.value.code == control_plane.READ_DEADLINE_CODE
    message = str(raised.value)
    assert f"Every one of {attempts} attempts expired" in message
    assert f"yoke deployment-runs get {RUN} release_lineage" in message
    assert QA_PENDING in message
    assert "omit member_closure" in message
    assert "control plane responsive" not in message


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


@pytest.mark.parametrize("code", sorted(control_plane.READ_CONNECTION_CODES))
def test_connection_failure_read_recovers(monkeypatch, sleeps, capsys, code):
    response = _expired()
    response.error.code = code
    dispatch = Mock(side_effect=[response, _answered({"unresolved": []})])
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)

    assert control_plane.unresolved_qa(RUN) == []
    assert dispatch.call_count == 2
    assert sleeps == [control_plane._READ_RETRY_BACKOFF_SECONDS[0]]
    assert f"answered {code}; reading again" in capsys.readouterr().err


@pytest.mark.parametrize("code", sorted(control_plane._READ_RETRY_CODES))
def test_exhausted_read_has_resume_hint(monkeypatch, sleeps, code):
    response = _expired()
    response.error.code = code
    response.error.message = "read unavailable"
    dispatch = Mock(return_value=response)
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)

    with pytest.raises(control_plane.DeploymentControlPlaneError) as raised:
        control_plane.unresolved_qa(RUN)

    assert dispatch.call_count == len(control_plane._READ_RETRY_BACKOFF_SECONDS) + 1
    assert sleeps == list(control_plane._READ_RETRY_BACKOFF_SECONDS)
    assert f"yoke watch deploy -- {RUN}" in str(raised.value)
    assert raised.value.code == code
    if code != control_plane.READ_DEADLINE_CODE:
        assert "connectivity remained unavailable" in str(raised.value)
        assert "attempts expired" not in str(raised.value)


@pytest.mark.parametrize("code", sorted(control_plane.READ_CONNECTION_CODES))
def test_connection_failure_write_is_not_retried(monkeypatch, sleeps, code):
    response = _expired("deployment_runs.execution.update")
    response.error.code = code
    dispatch = Mock(return_value=response)
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)
    expected = (control_plane.DeploymentOutcomeUnknown
                if code in control_plane.UNKNOWN_CODES
                else control_plane.DeploymentControlPlaneError)

    with pytest.raises(expected):
        control_plane.update_run_field(RUN, "current_stage", "deploy")

    assert dispatch.call_count == 1
    assert sleeps == []
