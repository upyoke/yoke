"""The deploy driver handles refused attachment responses without crashing."""

from unittest.mock import Mock

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain import deploy_pipeline_driver_client as driver_client
from yoke_core.domain import session_liveness_pump
from yoke_core.domain.control_plane_function_degradation import REGISTRY_SKEW_CODES
from yoke_core.domain.deployment_run_driver_attachment import (
    ATTACH_FUNCTION_ID,
    DRIVER_ALREADY_ATTACHED_CODE,
    ROW_LOCK_BUSY_CODE,
)


def _refusal(
    code: str, message: str = "attachment refused", result: dict | None = None
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=ATTACH_FUNCTION_ID,
        version="v1",
        result=result or {},
        error=FunctionError(code=code, message=message),
    )


def test_success_returns_the_attachment(monkeypatch):
    result = {"attached": True, "phase": "running"}
    dispatch = Mock(
        return_value=FunctionCallResponse(
            success=True, function=ATTACH_FUNCTION_ID, version="v1", result=result
        )
    )
    monkeypatch.setattr(driver_client, "call_dispatcher", dispatch)

    assert driver_client.attach_driver("run-driver", phase="running") == result
    assert dispatch.call_args.kwargs["target"].workflow_run_id == "run-driver"


@pytest.mark.parametrize("code", sorted(REGISTRY_SKEW_CODES))
def test_registry_skew_leaves_the_attachment_unrecorded(monkeypatch, code):
    monkeypatch.setattr(
        driver_client, "call_dispatcher", Mock(return_value=_refusal(code))
    )

    assert driver_client.attach_driver("run-driver", phase="running") == {}


def test_busy_row_reports_the_holder_and_leaves_attachment_unrecorded(
    monkeypatch, capsys
):
    message = "deployment_run_row_lock_busy: holder pid 42; retry after it releases"
    monkeypatch.setattr(
        driver_client,
        "call_dispatcher",
        Mock(return_value=_refusal(ROW_LOCK_BUSY_CODE, message)),
    )

    assert driver_client.attach_driver("run-driver", phase="running") == {}
    assert capsys.readouterr().err == message + "\n"


@pytest.mark.parametrize(
    "response",
    [
        _refusal("permission_denied"),
        FunctionCallResponse(success=False, function=ATTACH_FUNCTION_ID, version="v1"),
    ],
)
def test_other_refusals_raise_the_control_plane_error(monkeypatch, response):
    monkeypatch.setattr(driver_client, "call_dispatcher", Mock(return_value=response))
    message = response.error.message if response.error else "request failed"

    with pytest.raises(control_plane.DeploymentControlPlaneError) as caught:
        driver_client.attach_driver("run-driver", phase="running")
    assert str(caught.value) == f"{ATTACH_FUNCTION_ID} failed: {message}"


@pytest.mark.parametrize(
    "code", [*sorted(REGISTRY_SKEW_CODES), ROW_LOCK_BUSY_CODE, "permission_denied"]
)
def test_due_pump_tick_survives_an_attachment_refusal(monkeypatch, code):
    dispatch = Mock(return_value=_refusal(code))
    monkeypatch.setattr(driver_client, "call_dispatcher", dispatch)
    heartbeat = Mock(return_value=True)
    monkeypatch.setattr(session_liveness_pump, "refresh_session_heartbeat", heartbeat)
    pump = driver_client.DriverLivenessPump(
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


MACHINE = "6f1c2b9e-0d4a-4c1e-9a52-3b7e8d1f0a11"
EXITED_PID = 987654


def _held_by(machine_id: str) -> FunctionCallResponse:
    return _refusal(
        DRIVER_ALREADY_ATTACHED_CODE,
        "deployment run run-driver already has a live driver",
        {"driver": {"pid": EXITED_PID, "machine_id": machine_id}},
    )


def _attached() -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function=ATTACH_FUNCTION_ID,
        version="v1",
        result={"recorded": True},
    )


@pytest.mark.parametrize(
    ("holder_machine", "gone", "supersedes"),
    [
        (MACHINE, True, True),
        (MACHINE, False, False),
        ("another-machine", True, False),
    ],
)
def test_a_refusal_by_an_exited_local_driver_supersedes_it(
    monkeypatch, capsys, holder_machine, gone, supersedes
):
    """Re-drive on the same machine does not wait out a dead pid's heartbeat."""
    dispatch = Mock(side_effect=[_held_by(holder_machine), _attached()])
    monkeypatch.setattr(driver_client, "call_dispatcher", dispatch)
    monkeypatch.setattr(driver_client, "_local_machine_id", lambda: MACHINE)
    monkeypatch.setattr(driver_client, "_process_gone", lambda pid: gone)

    if not supersedes:
        with pytest.raises(control_plane.DeploymentControlPlaneError) as caught:
            driver_client.attach_driver("run-driver", phase="executing")
        assert caught.value.code == DRIVER_ALREADY_ATTACHED_CODE
        dispatch.assert_called_once()
        return
    assert driver_client.attach_driver("run-driver", phase="executing") == {
        "recorded": True
    }
    first, second = (call.kwargs["payload"] for call in dispatch.call_args_list)
    assert first["machine_id"] == MACHINE and first["exited_driver_pid"] == 0
    assert second["exited_driver_pid"] == EXITED_PID
    assert f"pid {EXITED_PID} on this machine has exited" in capsys.readouterr().err


def test_a_refused_release_reports_the_reason_and_lets_shutdown_finish(
    monkeypatch, capsys
):
    """A busy row at exit must not take the watcher's exit sentinel with it."""
    message = "deploy run row lock blocked: re-run `yoke watch deploy -- run-driver`"
    monkeypatch.setattr(
        driver_client,
        "call_dispatcher",
        Mock(return_value=_refusal(ROW_LOCK_BUSY_CODE, message)),
    )

    assert driver_client.release_driver("run-driver") is None
    assert message in capsys.readouterr().err
