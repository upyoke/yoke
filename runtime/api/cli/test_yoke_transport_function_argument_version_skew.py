"""An older server rejecting a newly added argument is named as version skew."""

from __future__ import annotations

from yoke_cli.transport import function_version_skew
from yoke_cli.transport.function_version_skew import (
    ARGUMENT_SKEW_ERROR_CODE,
    retype_skew,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_contracts.function_serving_floors import declared_argument_floors

LAUNCH_CREATE = "session_control.launch.create"
LAUNCH_PREVIEW = "session_control.launch.preview"


def _request(function_id: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(session_id="s1"),
        target=TargetRef(kind="global"),
        request_id="req-1",
        payload=payload,
    )


def _refused(request: FunctionCallRequest, code: str) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(code=code, message="Extra inputs are not permitted"),
    )


def _retype(monkeypatch, request, response) -> FunctionCallResponse:
    monkeypatch.setattr(
        function_version_skew, "local_handshake_version", lambda: "2.0.0"
    )
    return retype_skew(response, request, server_version="1.0.0", env_name="prod")


def test_a_level_refused_as_payload_invalid_names_the_argument_floor(
    monkeypatch,
) -> None:
    request = _request(LAUNCH_CREATE, {"project": "yoke", "level": "SENIOR"})

    response = _retype(monkeypatch, request, _refused(request, "payload_invalid"))

    error = response.error
    assert error.code == ARGUMENT_SKEW_ERROR_CODE
    assert "argument level" in error.message
    assert "minimum serving version next-release" in error.message
    assert "env 'prod'" in error.message
    assert "client engine version 2.0.0" in error.message
    assert "server engine version 1.0.0" in error.message
    assert "Extra inputs are not permitted" in error.message
    assert "--surface" in error.recovery_hint
    assert "control-plane operator" in error.recovery_hint


def test_a_level_preview_refusal_is_retyped_the_same_way(monkeypatch) -> None:
    request = _request(LAUNCH_PREVIEW, {"project": "yoke", "level": "JUNIOR"})

    response = _retype(monkeypatch, request, _refused(request, "payload_invalid"))

    assert response.error.code == ARGUMENT_SKEW_ERROR_CODE


def test_payload_invalid_without_a_floored_argument_is_untouched(
    monkeypatch,
) -> None:
    request = _request(
        LAUNCH_CREATE, {"project": "yoke", "executor_surface": "claude-cli"}
    )
    refused = _refused(request, "payload_invalid")

    response = _retype(monkeypatch, request, refused)

    assert response.error.code == "payload_invalid"
    assert response.error.message == refused.error.message


def test_another_refusal_of_a_level_payload_is_untouched(monkeypatch) -> None:
    request = _request(LAUNCH_CREATE, {"project": "yoke", "level": "SENIOR"})

    response = _retype(monkeypatch, request, _refused(request, "permission_denied"))

    assert response.error.code == "permission_denied"


def test_a_successful_level_call_is_untouched(monkeypatch) -> None:
    request = _request(LAUNCH_CREATE, {"project": "yoke", "level": "SENIOR"})
    ok = FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"launch": {}},
    )

    assert _retype(monkeypatch, request, ok) is ok


def test_only_carried_arguments_count_toward_a_floor() -> None:
    assert set(declared_argument_floors(LAUNCH_CREATE, {"level": "SENIOR"})) == {
        "level"
    }
    assert declared_argument_floors(LAUNCH_CREATE, {"level": None}) == {}
    assert declared_argument_floors(LAUNCH_CREATE, {"level": ""}) == {}
    assert declared_argument_floors(LAUNCH_CREATE, None) == {}
    assert declared_argument_floors("items.get.run", {"level": "SENIOR"}) == {}
