"""The last lease release stops a cloud Test Machine while holding its lease."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import test_machine_power
from yoke_core.domain.deploy_remote import CommandResult
from yoke_core.domain.test_machine_power_stop import stop_released
from runtime.api.domain.test_deploy_remote import FakeRunner
from runtime.api.domain.test_test_machine_power import CLOUD, MAC, OK

RELEASED = [{"project": "yoke", "test_machine": "windows-lab"}]


def _json(value) -> CommandResult:
    return CommandResult(0, json.dumps(value), "")


def _ec2_actions(runner: FakeRunner) -> list[str]:
    return [call["argv"][2] for call in runner.calls]


def _ok(result) -> FunctionCallResponse:
    return FunctionCallResponse(success=True, function="f", version="v1", result=result)


@pytest.fixture
def control_plane(monkeypatch):
    """Fake the hold, the settings read and the hold release; record the calls."""
    state = SimpleNamespace(calls=[], held_by_other=False, settings=CLOUD)

    def dispatch(function_id, payload):
        state.calls.append(function_id)
        if function_id == "claims.coordination_claim.acquire_if_free":
            assert payload["key"] == "QA_HOST:windows-lab"
            if state.held_by_other:
                return FunctionCallResponse(
                    success=False,
                    function=function_id,
                    version="v1",
                    error=FunctionError(code="claim_held", message="held"),
                )
            return _ok({"claim": {"id": 91}})
        if function_id == "test_machine.get":
            return _ok({"settings": state.settings, "active_lease": {"id": 91}})
        assert function_id == "claims.coordination_claim.release"
        assert payload["claim_id"] == 91
        return _ok({})

    monkeypatch.setattr(test_machine_power, "_dispatch", dispatch)
    monkeypatch.setattr(test_machine_power, "_aws_env", lambda project: {})
    return state


def test_last_release_stops_the_host_under_its_own_hold(control_plane):
    runner = FakeRunner([_json(["running"]), _json(["54.0.0.1"]), OK])
    stop_released(RELEASED, runner=runner, emit=lambda _l: None)
    assert _ec2_actions(runner) == [
        "describe-instances",
        "describe-addresses",
        "stop-instances",
    ]
    assert control_plane.calls == [
        "claims.coordination_claim.acquire_if_free",
        "test_machine.get",
        "claims.coordination_claim.release",
    ]


def test_a_lease_taken_before_the_hold_keeps_the_host_running(control_plane):
    control_plane.held_by_other = True
    runner = FakeRunner()
    stop_released(RELEASED, runner=runner, emit=lambda _l: None)
    assert runner.calls == []
    assert control_plane.calls == ["claims.coordination_claim.acquire_if_free"]


def test_the_hold_is_released_even_when_the_stop_fails(control_plane):
    runner = FakeRunner(
        [_json(["running"]), _json(["54.0.0.1"]), CommandResult(1, "", "Denied")]
    )
    lines: list[str] = []
    stop_released(RELEASED, runner=runner, emit=lines.append)
    assert lines[-1].startswith("test_machine_power_stop_failed:")
    assert control_plane.calls[-1] == "claims.coordination_claim.release"


def test_a_host_without_instance_id_is_held_then_left_alone(control_plane):
    control_plane.settings = MAC
    runner = FakeRunner()
    stop_released(RELEASED, runner=runner, emit=lambda _l: None)
    assert runner.calls == []
    assert control_plane.calls[-1] == "claims.coordination_claim.release"


def test_a_host_without_elastic_ip_stays_running_with_a_named_reason(control_plane):
    runner = FakeRunner([_json(["running"]), _json([])])
    lines: list[str] = []
    stop_released(RELEASED, runner=runner, emit=lines.append)
    assert "stop-instances" not in _ec2_actions(runner)
    assert lines[0].startswith("test_machine_power_stop_skipped:")


def test_releasing_the_hold_does_not_re_enter_the_stop(control_plane, monkeypatch):
    original = test_machine_power._dispatch
    nested = []

    def dispatch(function_id, payload):
        response = original(function_id, payload)
        if function_id == "claims.coordination_claim.release":
            # The hold's own release frees the host and names it again.
            nested.append(stop_released(RELEASED, runner=FakeRunner()))
        return response

    monkeypatch.setattr(test_machine_power, "_dispatch", dispatch)
    stop_released(RELEASED, runner=FakeRunner([_json(["stopped"])]), emit=lambda _l: None)
    assert nested == [None]
    assert control_plane.calls.count("claims.coordination_claim.acquire_if_free") == 1


def test_a_server_without_the_hold_function_leaves_the_host_running(monkeypatch):
    def dispatch(function_id, payload):
        return FunctionCallResponse(
            success=False,
            function=function_id,
            version="v1",
            error=FunctionError(code="function_version_skew", message="floor"),
        )

    monkeypatch.setattr(test_machine_power, "_dispatch", dispatch)
    lines: list[str] = []
    stop_released(RELEASED, runner=FakeRunner(), emit=lines.append)
    assert lines[0].startswith("test_machine_power_hold_failed:")


def test_the_client_transport_stops_machines_a_response_names(monkeypatch):
    from yoke_cli.transport import settled_response

    seen = []
    monkeypatch.setattr(
        "yoke_core.domain.test_machine_power_stop.stop_released", seen.append
    )
    response = _ok({}).model_copy(update={"released_test_machines": RELEASED})
    assert settled_response.settle_response(response).success
    assert seen == [RELEASED]
    settled_response.settle_response(_ok({}))
    assert seen == [RELEASED]


def test_an_older_server_refusal_of_the_hold_names_its_floor():
    from yoke_cli.transport.function_version_skew import retype_skew
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )

    function_id = "claims.coordination_claim.acquire_if_free"
    request = FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="1", session_id="stopper"),
        target=TargetRef(kind="global"),
        payload={},
    )
    refused = FunctionCallResponse(
        success=False,
        function=function_id,
        version="v1",
        error=FunctionError(code="function_not_registered", message="unknown"),
    )
    error = retype_skew(refused, request, server_version="1.0.0", env_name="prod").error
    assert error.code == "function_version_skew"
    assert "minimum serving version next-release" in error.message


def test_a_response_from_an_older_server_names_no_machines():
    response = FunctionCallResponse.model_validate(
        {"success": True, "function": "f", "version": "v1", "result": {}}
    )
    assert response.released_test_machines == []
