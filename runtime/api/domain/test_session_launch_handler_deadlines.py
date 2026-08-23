"""Registered launch surfaces converge deadlines without relay traffic."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_store import get_launch
from runtime.api.domain.session_launch_test_support import (
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)


class _NoCloseConnection:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self) -> None:
        pass


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="1", session_id="caller"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _wire_handler(monkeypatch, conn) -> None:
    monkeypatch.setattr(handlers, "_open", lambda: _NoCloseConnection(conn))
    monkeypatch.setattr(handlers, "_resolve_project", lambda _conn, _project: 10)
    monkeypatch.setattr(
        handlers,
        "_authorization",
        lambda _conn, _request, _project_id: authorization(),
    )


def test_get_and_list_settle_deadlines_when_no_relay_is_running(monkeypatch) -> None:
    conn = launch_connection()
    add_relay(conn)
    fetched_launch = assigned_launch(conn, key="handler-get")
    listed_launch = assigned_launch(conn, key="handler-list")
    conn.execute("DELETE FROM session_relays")
    conn.commit()
    _wire_handler(monkeypatch, conn)
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_deadlines.utc_now",
        lambda: "2026-08-22T12:11:00Z",
    )

    fetched = handlers.handle_launch_get(
        _request("session.launch.get", {"launch_id": fetched_launch.launch_id})
    )
    listed = handlers.handle_launch_list(
        _request("session.launch.list", {"project": "launch-project"})
    )

    assert fetched.primary_success
    assert fetched.result_payload["launch"]["state"] == "expired"
    states = {
        row["launch_id"]: row["state"] for row in listed.result_payload["launches"]
    }
    assert states[listed_launch.launch_id] == "expired"


def test_retry_mutation_settles_deadline_before_applying_retry(monkeypatch) -> None:
    conn = launch_connection()
    add_relay(
        conn,
        last_seen_at="2026-08-22T12:10:30Z",
        connected_until="2026-08-22T12:30:00Z",
    )
    launch = assigned_launch(conn, key="handler-retry")
    _wire_handler(monkeypatch, conn)
    monkeypatch.setattr(handlers, "_fleet_policy", lambda *_args: 10)
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_deadlines.utc_now",
        lambda: "2026-08-22T12:11:00Z",
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_requests.utc_now",
        lambda: "2026-08-22T12:11:00Z",
    )

    retried = handlers.handle_launch_retry(
        _request("session.launch.retry", {"launch_id": launch.launch_id})
    )

    assert retried.primary_success, retried.error
    assert retried.result_payload["launch"]["state"] == "assigned"
    assert get_launch(conn, launch.launch_id).deadline_at == "2026-08-22T12:21:00Z"
