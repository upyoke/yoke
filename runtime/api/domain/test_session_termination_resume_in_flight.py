"""Termination refuses a worker a wake is already resuming."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.domain.test_session_termination import (
    _HandlerConnection,
    _add_open_message,
    _add_target_claim,
    _register_operator_and_target,
    _terminate,
    _termination_schema_and_events as _termination_fixture,  # noqa: F401 - autouse
)
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_contracts.session_control.resume import RESUME_INACTIVITY_SECONDS
from yoke_core.domain.handlers.session_termination import handle_session_terminate
from yoke_core.domain.session_termination import RESUME_IN_FLIGHT_CODE
from yoke_core.domain.sessions import SessionError


pytest_plugins = ("runtime.api.test_sessions",)


def _stamp(seconds_ago: int) -> str:
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_exit(conn, *, seconds_ago: int) -> None:
    conn.execute(
        "UPDATE harness_sessions SET native_process_gone_at=%s, "
        "native_process_gone_evidence='{\"exit_code\":0}', "
        "last_heartbeat=%s, last_tool_call_at=%s WHERE session_id='worker'",
        (_stamp(seconds_ago), _stamp(seconds_ago + 5), _stamp(seconds_ago + 5)),
    )
    conn.commit()


def _record_wake(
    conn, *, seconds_ago: int, result_code: str | None, attempt_id: str = "wake-1"
) -> None:
    completed = None if result_code is None else _stamp(max(seconds_ago - 30, 0))
    _add_open_message(conn)
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,started_at,"
        "completed_at,result_code) VALUES (%s,'message-1','worker','wake_relay',"
        "%s,%s,%s)",
        (attempt_id, _stamp(seconds_ago), completed, result_code),
    )
    conn.commit()


def _terminated(conn) -> bool:
    row = conn.execute(
        "SELECT terminated_at FROM harness_sessions WHERE session_id='worker'"
    ).fetchone()
    return bool(row["terminated_at"])


@pytest.mark.parametrize("result_code", [None, "wake_delivered", "resumed_running"])
def test_resume_started_after_recorded_exit_refuses_termination(
    conn, result_code
) -> None:
    _register_operator_and_target(conn)
    _add_target_claim(conn, item_id=930)
    _record_exit(conn, seconds_ago=600)
    _record_wake(conn, seconds_ago=60, result_code=result_code)

    with pytest.raises(SessionError) as refused:
        _terminate(conn)

    assert refused.value.code == RESUME_IN_FLIGHT_CODE
    message = str(refused.value)
    assert "resuming, not dead" in message
    assert "wake-1" in message
    assert "yoke say --session worker --stdin" in message
    assert "--allow-resume-in-flight" in message
    conn.rollback()
    assert not _terminated(conn)
    claim = conn.execute(
        "SELECT released_at FROM work_claims WHERE session_id='worker'"
    ).fetchone()
    assert claim["released_at"] is None


def test_override_terminates_a_resuming_session(conn, monkeypatch) -> None:
    events: list[dict] = []
    monkeypatch.setattr(
        "yoke_core.domain.session_termination.emit_session_terminated",
        lambda session_id, context: events.append(context),
    )
    _register_operator_and_target(conn)
    _record_exit(conn, seconds_ago=600)
    _record_wake(conn, seconds_ago=60, result_code=None)

    result = _terminate(conn, allow_resume_in_flight=True)

    assert result["session"]["terminated_at"]
    assert events[-1]["allow_resume_in_flight"] is True


@pytest.mark.parametrize(
    ("exit_ago", "wake_ago", "result_code"),
    [
        # The resumed process already reported its own exit.
        (60, 600, "wake_delivered"),
        # The wake never produced a process.
        (600, 60, "resume_never_started"),
        (600, 60, "native_turn_running"),
        # Quiet past resume custody's window: no longer evidence of life.
        (
            RESUME_INACTIVITY_SECONDS + 900,
            RESUME_INACTIVITY_SECONDS + 300,
            None,
        ),
    ],
)
def test_no_live_resume_leaves_termination_available(
    conn, exit_ago, wake_ago, result_code
) -> None:
    _register_operator_and_target(conn)
    _record_exit(conn, seconds_ago=exit_ago)
    _record_wake(conn, seconds_ago=wake_ago, result_code=result_code)

    assert _terminate(conn)["session"]["terminated_at"]


def test_public_terminate_names_refusal_and_honours_override(conn, monkeypatch) -> None:
    _register_operator_and_target(conn)
    _record_exit(conn, seconds_ago=600)
    _record_wake(conn, seconds_ago=60, result_code="wake_delivered")
    handler_conn = _HandlerConnection(conn)
    monkeypatch.setattr(
        "yoke_core.domain.handlers.session_termination.open_connection",
        lambda: handler_conn,
    )

    def call(**extra):
        return handle_session_terminate(
            FunctionCallRequest.model_validate(
                {
                    "function": "session_control.session.terminate",
                    "actor": {"actor_id": "41", "session_id": "operator"},
                    "target": {"kind": "global"},
                    "payload": {
                        "session_id": "worker",
                        "reason": "restaff onto another model",
                        **extra,
                    },
                }
            )
        )

    refused = call()
    assert not refused.primary_success
    assert refused.error.code == RESUME_IN_FLIGHT_CODE

    allowed = call(allow_resume_in_flight=True)
    assert allowed.primary_success
    assert _terminated(conn)
