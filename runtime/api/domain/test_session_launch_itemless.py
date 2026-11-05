"""Itemless raw-instruction launches skip item lookup and stay idempotent."""

from __future__ import annotations

from runtime.api.domain.session_launch_itemless_test_support import (
    _NoCloseConnection as _NoCloseConnection,
    _itemless_payload as _itemless_payload,
    _request as _request,
    _wire_create as _wire_create,
)


from yoke_core.domain.handlers import session_launch as handlers
from runtime.api.domain.session_launch_test_support import (
    add_relay,
    launch_connection,
)


def test_itemless_raw_create_skips_item_naming_and_replays(monkeypatch) -> None:
    conn = launch_connection()
    add_relay(conn, connected_until="2026-08-24T12:00:00Z")
    _wire_create(monkeypatch, conn)
    payload = _itemless_payload(key="itemless-raw")

    first = handlers.handle_launch_create(_request(payload))
    second = handlers.handle_launch_create(_request(payload))

    assert first.primary_success is True, first.error
    assert first.result_payload["launch"]["item_id"] is None
    assert "session_name" not in first.result_payload["launch"]
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
