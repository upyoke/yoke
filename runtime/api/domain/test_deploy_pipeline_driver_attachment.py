"""The deploy driver handles refused attachment responses without crashing."""

from unittest.mock import Mock

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain import session_liveness_pump
from yoke_core.domain.control_plane_function_degradation import REGISTRY_SKEW_CODES
from yoke_core.domain.deployment_run_driver_attachment import (
    ATTACH_FUNCTION_ID,
    ROW_LOCK_BUSY_CODE,
)


def _refusal(code: str, message: str = "attachment refused") -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=ATTACH_FUNCTION_ID,
        version="v1",
        error=FunctionError(code=code, message=message),
    )


def test_success_returns_the_attachment(monkeypatch):
    result = {"attached": True, "phase": "running"}
    dispatch = Mock(
        return_value=FunctionCallResponse(
            success=True, function=ATTACH_FUNCTION_ID, version="v1", result=result
        )
    )
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)

    assert control_plane.attach_driver("run-driver", phase="running") == result
    assert dispatch.call_args.kwargs["target"].workflow_run_id == "run-driver"


@pytest.mark.parametrize("code", sorted(REGISTRY_SKEW_CODES))
def test_registry_skew_leaves_the_attachment_unrecorded(monkeypatch, code):
    monkeypatch.setattr(
        control_plane, "call_dispatcher", Mock(return_value=_refusal(code))
    )

    assert control_plane.attach_driver("run-driver", phase="running") == {}


def test_busy_row_reports_the_holder_and_leaves_attachment_unrecorded(
    monkeypatch, capsys
):
    message = "deployment_run_row_lock_busy: holder pid 42; retry after it releases"
    monkeypatch.setattr(
        control_plane,
        "call_dispatcher",
        Mock(return_value=_refusal(ROW_LOCK_BUSY_CODE, message)),
    )

    assert control_plane.attach_driver("run-driver", phase="running") == {}
    assert capsys.readouterr().err == message + "\n"


@pytest.mark.parametrize(
    "response",
    [
        _refusal("permission_denied"),
        FunctionCallResponse(success=False, function=ATTACH_FUNCTION_ID, version="v1"),
    ],
)
def test_other_refusals_raise_the_control_plane_error(monkeypatch, response):
    monkeypatch.setattr(control_plane, "call_dispatcher", Mock(return_value=response))
    message = response.error.message if response.error else "request failed"

    with pytest.raises(control_plane.DeploymentControlPlaneError) as caught:
        control_plane.attach_driver("run-driver", phase="running")
    assert str(caught.value) == f"{ATTACH_FUNCTION_ID} failed: {message}"


@pytest.mark.parametrize(
    "code", [*sorted(REGISTRY_SKEW_CODES), ROW_LOCK_BUSY_CODE, "permission_denied"]
)
def test_due_pump_tick_survives_an_attachment_refusal(monkeypatch, code):
    dispatch = Mock(return_value=_refusal(code))
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)
    heartbeat = Mock(return_value=True)
    monkeypatch.setattr(session_liveness_pump, "refresh_session_heartbeat", heartbeat)
    pump = control_plane.DriverLivenessPump(
        "run-driver",
        phase="running",
        progress_capture="driver.log",
        interval_seconds=10,
    )
    pump._session_id = "driver-session"
    pump._resolved = True
    pump._last_refresh = 0
    pump._clock = lambda: 10

    assert pump.tick() is True
    heartbeat.assert_called_once_with("driver-session")
    dispatch.assert_called_once()
    assert dispatch.call_args.kwargs["payload"]["progress_capture"] == "driver.log"
    assert pump.tick() is False
    dispatch.assert_called_once()
