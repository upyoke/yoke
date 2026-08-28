"""Registered launch surfaces converge deadlines without relay traffic."""

from __future__ import annotations

import json

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_store import get_launch
from runtime.api.domain.session_launch_test_support import (
    NOW,
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
        "yoke_core.domain.session_launch_requests.utc_now",
        lambda: NOW,
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_surface_selection.utc_now",
        lambda: NOW,
    )
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


def test_create_reads_the_organization_surface_fallback_gate(monkeypatch) -> None:
    conn = launch_connection()
    conn.execute("ALTER TABLE projects ADD COLUMN org_id INTEGER DEFAULT 1")
    conn.execute(
        "CREATE TABLE organizations (id INTEGER PRIMARY KEY,settings TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO organizations VALUES (1,'{}')")
    conn.commit()
    add_relay(
        conn,
        surface="codex-cli",
        connected_until="2026-08-24T12:00:00Z",
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_assignment.assignment_session_name",
        lambda *_args, **_kwargs: "YOK-41: Surface fallback fixture",
    )
    _wire_handler(monkeypatch, conn)
    payload = {
        "project": "launch-project",
        "item": "YOK-41",
        "executor_surface": "codex-vscode",
        "instructions": "Use an explicitly selected same-family surface.",
        "idempotency_key": "policy-off",
        "allow_surface_fallback": True,
    }

    disabled = handlers.handle_launch_create(_request("session.launch.create", payload))
    conn.execute(
        "UPDATE organizations SET settings=? WHERE id=1",
        (json.dumps({"fleet": {"surface_fallback": True}}),),
    )
    conn.commit()
    enabled = handlers.handle_launch_create(
        _request(
            "session.launch.create",
            {**payload, "idempotency_key": "policy-on"},
        )
    )

    assert disabled.primary_success is False
    assert disabled.error and disabled.error.code == "surface_fallback_disabled"
    assert enabled.primary_success is True
    assert enabled.result_payload["launch"]["requested_surface"] == "codex-vscode"
    assert enabled.result_payload["launch"]["selected_surface"] == "codex-cli"


def test_preview_reads_the_organization_machine_auto_selection_gate(
    monkeypatch,
) -> None:
    conn = launch_connection()
    add_relay(
        conn,
        relay_id="relay-b",
        machine_id="machine-b",
        connected_until="2026-08-24T12:00:00Z",
    )
    add_relay(
        conn,
        relay_id="relay-a",
        machine_id="machine-a",
        connected_until="2026-08-24T12:00:00Z",
    )
    _wire_handler(monkeypatch, conn)
    monkeypatch.setattr(
        handlers,
        "_fleet_policy",
        lambda _conn, _project_id, key: key == "fleet.auto_select_machine",
    )

    result = handlers.handle_launch_preview(
        _request(
            "session.launch.preview",
            {
                "project": "launch-project",
                "executor_surface": "codex-cli",
                "model": "gpt-5.6-sol",
            },
        )
    )

    assert result.primary_success is True
    assert result.result_payload["outcome"] == "assigned"
    assert result.result_payload["requested_model"] == "gpt-5.6-sol"
    assert result.result_payload["selected_relay"]["machine_id"] == "machine-a"
