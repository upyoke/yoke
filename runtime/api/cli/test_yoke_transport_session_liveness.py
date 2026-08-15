"""Client-local long waits refresh their owning harness session."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from yoke_cli.commands.adapters import github_actions_run_wait, github_actions_wait
from yoke_cli.transport.session_liveness import (
    ClientSessionLiveness,
    refresh_session_heartbeat,
)
from yoke_contracts.api.function_call import ActorContext, FunctionCallResponse


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_refresh_dispatches_the_registered_session_touch() -> None:
    calls: list[dict] = []
    actor = ActorContext(session_id="session-1")

    def dispatch(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(success=True)

    assert refresh_session_heartbeat(actor, dispatch=dispatch)
    assert len(calls) == 1
    call = calls[0]
    assert call["function_id"] == "sessions.touch"
    assert call["target"].kind == "global"
    assert call["payload"] == {}
    assert call["actor"] == actor
    assert call["intent"] == "long command liveness"


def test_refresh_failure_never_replaces_the_wait_result() -> None:
    def unavailable(**_kwargs):
        raise RuntimeError("transport unavailable")

    actor = ActorContext(session_id="session-1")
    assert not refresh_session_heartbeat(actor, dispatch=unavailable)


def test_poll_ticks_refresh_only_when_the_cadence_is_due() -> None:
    clock = Clock()
    calls: list[str] = []
    actor = ActorContext(session_id="session-1")
    liveness = ClientSessionLiveness(
        actor,
        interval_seconds=60,
        clock=clock,
        dispatch=lambda **kwargs: (
            calls.append(kwargs["function_id"])
            or SimpleNamespace(success=True)
        ),
    )

    assert not liveness.tick()
    clock.now = 60
    assert liveness.tick()
    assert not liveness.tick()
    assert calls == ["sessions.touch"]


def _recording_liveness(events: list[object]):
    class RecordingLiveness:
        def __init__(self, actor, *, interval_seconds):
            events.append(("init", actor.session_id, interval_seconds))

        def tick(self):
            events.append("tick")
            return True

    return RecordingLiveness


def _response(function: str, state: str) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function=function,
        version="v1",
        request_id="request-1",
        result={"state": state, "message": state},
    )


def test_check_ci_wait_ticks_liveness_inside_the_poll_scope() -> None:
    events: list[object] = []
    with (
        patch.object(github_actions_wait, "ensure_handlers_loaded"),
        patch.object(
            github_actions_wait,
            "ClientSessionLiveness",
            _recording_liveness(events),
        ),
        patch.object(github_actions_wait, "_next_read_delay", return_value=60),
        patch.object(
            github_actions_wait,
            "call_dispatcher",
            return_value=_response("github_actions.check_ci", "passed"),
        ),
    ):
        result = github_actions_wait.wait_for_ci_completion(
            {"repo": "o/r", "workflow": "ci.yml", "project": "yoke"},
            session_id="session-1",
            json_mode=False,
            timeout_sec=600,
        )

    assert result == 0
    assert events == [("init", "session-1", 60), "tick"]


def test_wait_run_ticks_liveness_inside_the_poll_scope() -> None:
    events: list[object] = []
    with (
        patch.object(github_actions_run_wait, "ensure_handlers_loaded"),
        patch.object(
            github_actions_run_wait,
            "ClientSessionLiveness",
            _recording_liveness(events),
        ),
        patch.object(
            github_actions_run_wait,
            "call_dispatcher",
            return_value=_response("github_actions.wait_run", "success"),
        ),
    ):
        result = github_actions_run_wait.wait_for_run_completion(
            {"repo": "o/r", "run_id": "1", "project": "yoke"},
            session_id="session-1",
            json_mode=False,
            timeout_sec=600,
        )

    assert result == 0
    assert events == [
        ("init", "session-1", github_actions_run_wait.RUN_WAIT_POLL_INTERVAL_SEC),
        "tick",
    ]
