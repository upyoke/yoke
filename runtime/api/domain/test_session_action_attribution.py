"""A session-affecting call lands in the target session's own history."""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)
from yoke_core.domain import session_action_attribution
from yoke_core.domain.session_action_attribution import (
    EVENT_SESSION_ACTION_PERFORMED,
    action_label,
    record_session_action,
    target_session_ids,
)


def _request(
    function: str, payload: dict, *, actor_id: str = "10"
) -> FunctionCallRequest:
    return FunctionCallRequest.model_validate(
        {
            "function": function,
            "actor": {"actor_id": actor_id, "session_id": "caller-session"},
            "target": {"kind": "global"},
            "payload": payload,
        }
    )


def _response(function: str, result: dict, *, success: bool = True):
    return FunctionCallResponse(
        success=success,
        function=function,
        version="v1",
        request_id="req-1",
        result=result,
        warnings=[],
        error=None,
        event_ids=[],
    )


def _capture(monkeypatch) -> list[dict[str, Any]]:
    emitted: list[dict[str, Any]] = []

    def _fake_emit(event_name: str, **kwargs: Any) -> None:
        emitted.append({"event_name": event_name, **kwargs})

    monkeypatch.setattr("yoke_core.domain.events.emit_event", _fake_emit, raising=True)
    return emitted


def test_action_label_covers_every_session_affecting_function() -> None:
    for function_id in session_action_attribution.SESSION_ACTION_LABELS:
        assert action_label(function_id)
    assert action_label("items.create") is None


def test_target_ids_read_payload_and_result_halves() -> None:
    assert target_session_ids(
        "session_control.keepalive.hold", {"session_id": "worker-1"}, {}
    ) == ("worker-1",)
    assert target_session_ids(
        "session_control.session.wake",
        {"public_ref": "ALP-1"},
        {"target_session_id": "worker-2"},
    ) == ("worker-2",)
    assert target_session_ids(
        "session_control.message.send",
        {},
        {"recipients": [{"session_id": "a"}, {"session_id": "b"}]},
    ) == ("a", "b")
    assert target_session_ids(
        "session_control.session.terminate",
        {"session_id": "worker-3"},
        {"session": {"session_id": "worker-3"}},
    ) == ("worker-3",)
    assert (
        target_session_ids(
            "session_control.launch.create",
            {},
            {"launch": {"registered_session_id": None}},
        )
        == ()
    )
    assert target_session_ids("items.create", {"session_id": "x"}, {}) == ()


def test_each_action_records_the_acting_actor_on_the_target(monkeypatch) -> None:
    emitted = _capture(monkeypatch)
    cases = (
        ("session_control.message.send", {}, {"recipients": [{"session_id": "w1"}]}),
        ("session_control.session.wake", {"session_id": "w1"}, {}),
        ("session_control.session.terminate", {"session_id": "w1"}, {}),
        ("session_control.keepalive.hold", {"session_id": "w1"}, {}),
        ("session_control.keepalive.release", {"session_id": "w1"}, {}),
        (
            "session_control.launch.retry",
            {},
            {"launch": {"registered_session_id": "w1"}},
        ),
    )
    for function_id, payload, result in cases:
        record_session_action(
            _request(function_id, payload),
            function_id,
            _response(function_id, result),
            project="alpha",
        )
    assert len(emitted) == len(cases)
    for event, (function_id, _payload, _result) in zip(emitted, cases):
        assert event["event_name"] == EVENT_SESSION_ACTION_PERFORMED
        assert event["session_id"] == "w1"
        assert event["auth_context"].actor_id == 10
        assert event["context"]["function"] == function_id
        assert event["context"]["performed_by_session_id"] == "caller-session"
        assert event["context"]["performed_by_actor_id"] == "10"


def test_a_failed_action_is_recorded_as_failed(monkeypatch) -> None:
    emitted = _capture(monkeypatch)
    function_id = "session_control.session.terminate"
    record_session_action(
        _request(function_id, {"session_id": "w1"}),
        function_id,
        _response(function_id, {}, success=False),
    )
    assert emitted[0]["outcome"] == "failed"


def test_a_session_acting_on_itself_writes_no_second_row(monkeypatch) -> None:
    emitted = _capture(monkeypatch)
    function_id = "session_control.keepalive.hold"
    record_session_action(
        _request(function_id, {"session_id": "caller-session"}),
        function_id,
        _response(function_id, {}),
    )
    assert emitted == []


def test_an_unattributed_call_records_nothing(monkeypatch) -> None:
    emitted = _capture(monkeypatch)
    function_id = "session_control.session.wake"
    record_session_action(
        _request(function_id, {"session_id": "w1"}, actor_id=""),
        function_id,
        _response(function_id, {}),
    )
    assert emitted == []


def test_an_emission_failure_never_fails_the_action(monkeypatch) -> None:
    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("events table unavailable")

    monkeypatch.setattr("yoke_core.domain.events.emit_event", _boom, raising=True)
    function_id = "session_control.session.terminate"
    record_session_action(
        _request(function_id, {"session_id": "w1"}),
        function_id,
        _response(function_id, {}),
    )
