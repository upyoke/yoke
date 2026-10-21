"""A self-deploy driver sends its calls over https whenever the paired API answers.

On a `*-db-admin` door a declared self-deploy may run any handler locally,
but every local query is a tunnel round trip. Each call goes to the paired
https env first; the door answers only what that env cannot serve.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from yoke_cli.transport import dispatcher
from yoke_cli.transport.relay_telemetry import TRANSPORT_FAILED_CODE
from yoke_contracts import direct_database_access as door
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import deploy_pipeline_driver_client as driver_client
from yoke_core.domain.deployment_qa_stage_dispatch import (
    DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
    dispatch_deployment_qa_stage,
)

pytestmark = pytest.mark.usefixtures("bound_project_context")

ADMIN_ENV = "prod-db-admin"
SERVED_ENV = "prod"
PAIRED = {
    "connections": {
        ADMIN_ENV: {"transport": "local-postgres", "prod": True},
        SERVED_ENV: {"transport": "https", "api_url": "https://control.example/v1"},
    }
}
CONNECTION = SimpleNamespace(env=SERVED_ENV, api_url="https://control.example/v1")


def _answer(request: Any, **fields: Any) -> FunctionCallResponse:
    return FunctionCallResponse(
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        **fields,
    )


class Planes:
    """Records which plane answered each call; https answers as told."""

    def __init__(self) -> None:
        self.https: list[tuple[str, str, Any]] = []
        self.door: list[tuple[str, str]] = []
        self.connection: Any = CONNECTION
        self.https_error: FunctionError | None = None

    def resolve(self, explicit_env: str | None = None) -> Any:
        # The selected door itself is not an https connection.
        return self.connection if explicit_env == SERVED_ENV else None

    def relay(self, request: Any, https: Any, **kwargs: Any) -> FunctionCallResponse:
        self.https.append((request.function, request.request_id, kwargs["max_attempts"]))
        if self.https_error is not None:
            return _answer(request, success=False, error=self.https_error)
        return _answer(request, success=True, result={"code": 0, "driver": "x"})

    def local(self, request: Any, _dispatch: Any, core_available: bool) -> Any:
        self.door.append((request.function, request.request_id))
        return _answer(request, success=True, result={"code": 0, "driver": "x"})


@pytest.fixture
def planes(monkeypatch) -> Planes:
    runtime = door.machine_config_runtime
    monkeypatch.setattr(runtime, "active_env", lambda **_kwargs: ADMIN_ENV)
    monkeypatch.setattr(runtime, "load_config", lambda *_a, **_kw: PAIRED)
    monkeypatch.setenv(door.DECLARED_COMMAND_ENV, door.SELF_DEPLOY_EXECUTE_COMMAND)
    recorded = Planes()
    transport = dispatcher.https_transport
    monkeypatch.setattr(transport, "resolve_https_connection", recorded.resolve)
    monkeypatch.setattr(transport, "relay_https", recorded.relay)
    monkeypatch.setattr(dispatcher, "warn_if_behind_active_connection", lambda **kw: None)
    monkeypatch.setattr(
        dispatcher.local_github_dispatch,
        "call_with_machine_github_authorization",
        recorded.local,
    )
    monkeypatch.setattr(driver_client, "_local_machine_id", lambda: "machine-1")
    return recorded


def _drive() -> None:
    dispatch_deployment_qa_stage({"name": "item-qa"}, run_id="run-1")
    driver_client.attach_driver("run-1", phase="executing")


def test_dispatch_and_execution_calls_go_over_https(planes, capsys):
    _drive()

    assert [call[0] for call in planes.https] == [
        DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
        driver_client.ATTACH_FUNCTION_ID,
    ]
    # One attempt each: a down API falls to the door, not a retry ladder.
    assert {call[2] for call in planes.https} == {1}
    assert planes.door == []
    assert "self-deploy database door" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "unserved",
    [
        pytest.param({"connection": None}, id="no-https-connection"),
        pytest.param(
            {"https_error": FunctionError(code=TRANSPORT_FAILED_CODE, message="down")},
            id="api-unreachable",
        ),
        pytest.param(
            {"https_error": FunctionError(code="function_version_skew", message="old")},
            id="serving-build-lacks-function",
        ),
    ],
)
def test_calls_https_cannot_serve_fall_back_to_the_door(planes, capsys, unserved):
    for name, value in unserved.items():
        setattr(planes, name, value)

    _drive()

    assert [call[0] for call in planes.door] == [
        DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
        driver_client.ATTACH_FUNCTION_ID,
    ]
    # The door re-sends the same request, so an applied call replays.
    assert [call[1] for call in planes.https] == [call[1] for call in planes.door][
        : len(planes.https)
    ]
    notes = [
        line for line in capsys.readouterr().err.splitlines() if "door" in line
    ]
    assert len(notes) == 2
    assert notes[0].startswith(f"note: {SERVED_ENV!r} could not serve ")
    assert notes[0].endswith("sending it through the self-deploy database door")


def test_a_served_refusal_is_the_answer(planes):
    planes.https_error = FunctionError(code="permission_denied", message="no")

    response = dispatcher.call_dispatcher(
        function_id=DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
        target=dispatcher.TargetRef(kind="workflow_run", workflow_run_id="run-1"),
        payload={"stage_name": "item-qa"},
    )

    assert response.error is not None and response.error.code == "permission_denied"
    assert planes.door == []


def test_database_functions_stay_on_the_door(planes):
    dispatcher.call_dispatcher(
        function_id="db.read.run",
        target=dispatcher.TargetRef(kind="global"),
        payload={"sql": "SELECT 1"},
    )

    assert planes.https == []
    assert [call[0] for call in planes.door] == ["db.read.run"]


def test_without_the_declaration_the_door_still_refuses_routine_calls(
    planes, monkeypatch
):
    monkeypatch.delenv(door.DECLARED_COMMAND_ENV)

    response = dispatcher.call_dispatcher(
        function_id=DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
        target=dispatcher.TargetRef(kind="workflow_run", workflow_run_id="run-1"),
        payload={"stage_name": "item-qa"},
    )

    assert response.error is not None and response.error.code == door.USE_HTTPS_ENV
    assert planes.https == [] and planes.door == []
