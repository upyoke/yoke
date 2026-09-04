# ruff: noqa: F811
"""Registered session-touch reasons for working and unchanged modes."""

from __future__ import annotations

from runtime.api.test_sessions import _register, conn  # noqa: F401
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import sessions_orchestration


def _request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="sessions.touch",
        actor=ActorContext(actor_id="2", session_id="sess-1"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _touch(conn, monkeypatch, payload: dict) -> dict:
    monkeypatch.setattr(sessions_orchestration, "_connect_rw", lambda: conn)
    outcome = sessions_orchestration.handle_touch(_request(payload))
    assert outcome.primary_success is True
    return outcome.result_payload["session"]


def test_reason_is_accepted_with_a_working_mode(conn, monkeypatch):
    _register(conn)

    session = _touch(
        conn,
        monkeypatch,
        {"mode": "dash", "reason": "waiting on CI"},
    )

    assert session["mode"] == "dash"
    assert session["quiet_reason"] == "waiting on CI"


def test_reason_is_accepted_without_changing_mode(conn, monkeypatch):
    _register(conn, mode="dash")
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s WHERE session_id=%s",
        ("2026-01-01T00:00:00Z", "sess-1"),
    )
    conn.commit()

    session = _touch(conn, monkeypatch, {"reason": "waiting on merge queue"})

    assert session["mode"] == "dash"
    assert session["quiet_reason"] == "waiting on merge queue"
    assert session["last_heartbeat"] != "2026-01-01T00:00:00Z"
