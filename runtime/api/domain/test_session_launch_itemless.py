"""Itemless raw-instruction launches skip item lookup and stay idempotent."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import session_launch as handlers
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
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


def _request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="session.launch.create",
        actor=ActorContext(actor_id="1", session_id="caller"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _fleet_policy(_conn, _project_id, path: str):
    if path == "fleet.launch_deadline_minutes":
        return 10
    if path == "fleet.max_body_bytes":
        return 65536
    return False


def _wire_create(monkeypatch, conn) -> None:
    monkeypatch.setattr(handlers, "_open", lambda: _NoCloseConnection(conn))
    monkeypatch.setattr(handlers, "_resolve_project", lambda _conn, _project: 10)
    monkeypatch.setattr(handlers, "_authorization", lambda *_a, **_k: authorization())
    monkeypatch.setattr(handlers, "_fleet_policy", _fleet_policy)
    monkeypatch.setattr("yoke_core.domain.session_launch_requests.utc_now", lambda: NOW)
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_surface_selection.utc_now",
        lambda: NOW,
    )


def _itemless_payload(*, key: str, instructions: str = "Custom full body.") -> dict:
    return {
        "project": "launch-project",
        "executor_surface": "codex-cli",
        "instructions": instructions,
        "idempotency_key": key,
        "compose_mandate": False,
    }


def test_itemless_raw_create_skips_item_naming_and_replays(monkeypatch) -> None:
    conn = launch_connection()
    add_relay(conn, connected_until="2026-08-24T12:00:00Z")
    _wire_create(monkeypatch, conn)
    payload = _itemless_payload(key="itemless-raw")

    first = handlers.handle_launch_create(_request(payload))
    second = handlers.handle_launch_create(_request(payload))

    assert first.primary_success is True, first.error
    assert not first.result_payload["launch"].get("session_name")
    assert second.primary_success is True, second.error
    assert second.result_payload["deduplicated"] is True
    assert (
        second.result_payload["launch"]["launch_id"]
        == first.result_payload["launch"]["launch_id"]
    )
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 1


def test_composed_create_without_item_is_payload_invalid(monkeypatch) -> None:
    conn = launch_connection()
    add_relay(conn, connected_until="2026-08-24T12:00:00Z")
    _wire_create(monkeypatch, conn)

    outcome = handlers.handle_launch_create(
        _request(
            {
                "project": "launch-project",
                "executor_surface": "codex-cli",
                "idempotency_key": "composed-missing",
            }
        )
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"


def test_itemless_raw_without_body_is_payload_invalid(monkeypatch) -> None:
    conn = launch_connection()
    add_relay(conn, connected_until="2026-08-24T12:00:00Z")
    _wire_create(monkeypatch, conn)

    outcome = handlers.handle_launch_create(
        _request(_itemless_payload(key="raw-empty", instructions="  "))
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
